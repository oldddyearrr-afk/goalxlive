#!/bin/bash
set -e

HLS_ROOT="/var/www/html/hls"
mkdir -p "${HLS_ROOT}"

# *** CONFIG: ضع هنا قنواتك ***
# صيغة: CH_ID|MASTER_M3U8_URL
CHANNELS=(
  "ch1|http://176.119.29.42/0c55573d-12d8-43af-823b-25c94d67b190.m3u8"
  "ch2|https://live-goalx.goalx.workers.dev/b1/auto.m3u8"
  # أضف المزيد هنا بصيغة: "ch3|https://..."
)

# دالة لبدء ffmpeg لنسخ المصدر إلى HLS ملف
start_copy_stream() {
  local CH=$1
  local LABEL=$2   # e.g. BANDWIDTH_1000000 أو custom
  local SRC=$3
  local OUTDIR="${HLS_ROOT}/${CH}/${LABEL}"
  mkdir -p "${OUTDIR}"

  # اسم ملفات القطع
  local SEG="${OUTDIR}/seg_%05d.ts"
  local PLAY="${OUTDIR}/index.m3u8"

  # ffmpeg command (copy codec, create HLS, حذف القطع القديمة)
  while true; do
    echo "Starting ffmpeg for ${CH}/${LABEL} -> ${PLAY}"
    ffmpeg -hide_banner -loglevel warning -y -i "${SRC}" \
      -c copy \
      -hls_time 6 \
      -hls_list_size 6 \
      -hls_flags delete_segments+split_by_time \
      -hls_segment_filename "${SEG}" \
      "${PLAY}"
    echo "ffmpeg exited for ${CH}/${LABEL} — restarting in 3s"
    sleep 3
  done &
}

# process each channel
for item in "${CHANNELS[@]}"; do
  CH_ID=$(echo "$item" | cut -d'|' -f1)
  SRC_URL=$(echo "$item" | cut -d'|' -f2)

  echo "Processing channel ${CH_ID} -> ${SRC_URL}"
  # call parser to list variants if master playlist
  /scripts/parse_variants.sh "${CH_ID}" "${SRC_URL}"

  VARLIST_DIR="/var/www/html/hls/${CH_ID}"
  # if parser placed variants_labelled.list -> spawn per variant
  if [ -f "${VARLIST_DIR}/variants_labelled.list" ]; then
    while IFS='|' read -r LABEL FULLURL; do
      if [ -n "$LABEL" ] && [ -n "$FULLURL" ]; then
        start_copy_stream "${CH_ID}" "${LABEL}" "${FULLURL}"
      fi
    done < "${VARLIST_DIR}/variants_labelled.list"
  else
    # else single stream (parser wrote source.url)
    if [ -f "${VARLIST_DIR}/source.url" ]; then
      SRC=$(cat "${VARLIST_DIR}/source.url")
      start_copy_stream "${CH_ID}" "main" "${SRC}"
    else
      echo "No variants found for ${CH_ID}, attempting direct start on provided URL"
      start_copy_stream "${CH_ID}" "main" "${SRC_URL}"
    fi
  fi
done

# start nginx in foreground
nginx -g "daemon off;"
