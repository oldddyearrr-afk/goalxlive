#!/bin/bash
# usage: parse_variants.sh <channel_id> <master_m3u8_url>
# ex: ./parse_variants.sh ch1 "https://source.example/master.m3u8"

CH_ID="$1"
MASTER="$2"
OUTDIR="/var/www/html/hls/${CH_ID}"
mkdir -p "${OUTDIR}"

TMP="/tmp/${CH_ID}_master.m3u8"
curl -fsSL "$MASTER" -o "${TMP}" || { echo "Failed to fetch master"; exit 1; }

# if already a media playlist (not master), just create single entry
if ! grep -E "^#EXT-X-STREAM-INF" "${TMP}" >/dev/null; then
  # single quality stream -> spawn one ffmpeg to copy
  echo "single-quality or direct media playlist detected"
  echo "$MASTER" > "${OUTDIR}/source.url"
  exit 0
fi

# parse variants: find lines with EXT-X-STREAM-INF and following URI
awk 'BEGIN{RS="\n"} /#EXT-X-STREAM-INF/{ getline; print $0 }' "${TMP}" | while read -r VARIANT_URL; do
  # resolve relative URLs:
  if [[ "${VARIANT_URL}" =~ ^http ]]; then
    FULL="${VARIANT_URL}"
  else
    BASE=$(dirname "$MASTER")
    FULL="${BASE}/${VARIANT_URL}"
  fi

  # try to get a label (bandwidth or resolution) from the EXT-X-STREAM-INF line
  # find the preceding line with EXT-X-STREAM-INF and extract BANDWIDTH or RESOLUTION
  LABEL=$(grep -B1 -F "$VARIANT_URL" "${TMP}" | head -n1 | sed -E 's/.*(BANDWIDTH=[0-9]+|RESOLUTION=[0-9x]+).*/\1/' | tr '=' '_' )
  if [ -z "$LABEL" ]; then
    # fallback to timestamp
    LABEL="v$(date +%s%N)"
  fi

  # sanitize label
  SAFE_LABEL=$(echo "$LABEL" | tr '/:' '_' | tr -cd '[:alnum:]_-.')
  echo "$FULL" >> "${OUTDIR}/variants.list"
  echo "$SAFE_LABEL|$FULL" >> "${OUTDIR}/variants_labelled.list"
done

echo "Variants for ${CH_ID} written to ${OUTDIR}/variants_labelled.list"
