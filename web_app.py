#!/usr/bin/env python3
from flask import Flask, render_template, jsonify, request
import subprocess
import os
import json
from datetime import datetime
from pathlib import Path
import uuid

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
TELEGRAM_STREAMS_FILE = BASE_DIR / "telegram_streams.json"

def load_telegram_streams():
    """تحميل قائمة بثوث تليجرام من الملف"""
    if TELEGRAM_STREAMS_FILE.exists():
        with open(TELEGRAM_STREAMS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_telegram_streams(streams):
    """حفظ قائمة بثوث تليجرام"""
    with open(TELEGRAM_STREAMS_FILE, 'w', encoding='utf-8') as f:
        json.dump(streams, f, ensure_ascii=False, indent=2)

def get_stream_status(session_name):
    """التحقق من حالة بث معين"""
    try:
        result = subprocess.run(
            ['tmux', 'has-session', '-t', session_name],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except:
        return False

@app.route('/')
def index():
    """الصفحة الرئيسية - تليجرام مباشرة"""
    return render_template('telegram_index.html')

@app.route('/health')
def health():
    """Health check endpoint for monitoring"""
    import psutil
    process = psutil.Process()
    mem_info = process.memory_info()
    return jsonify({
        'status': 'ok',
        'memory_mb': round(mem_info.rss / 1024 / 1024, 2),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/telegram/streams')
def api_telegram_streams():
    """الحصول على قائمة جميع بثوث تليجرام"""
    streams = load_telegram_streams()
    for stream in streams:
        stream['status'] = 'running' if get_stream_status(stream['session_name']) else 'stopped'
    save_telegram_streams(streams)
    return jsonify({'streams': streams})

@app.route('/api/telegram/stream/add', methods=['POST'])
def api_telegram_add_stream():
    """إضافة بث تليجرام جديد"""
    session_name = None
    try:
        data = request.get_json() or {}
        stream_key = data.get('stream_key', '').strip()
        stream_name = data.get('stream_name', '').strip()
        source_url = data.get('source_url', '').strip()

        if not stream_key:
            return jsonify({'success': False, 'error': 'يرجى إدخال مفتاح البث (RTMP URL)'}), 400

        if not stream_name:
            stream_name = f'بث تليجرام {datetime.now().strftime("%H:%M:%S")}'

        stream_id = str(uuid.uuid4())[:8]
        session_name = f'tgstream_{stream_id}'

        streams = load_telegram_streams()

        new_stream = {
            'id': stream_id,
            'session_name': session_name,
            'name': stream_name,
            'stream_key': stream_key[:30] + '...',
            'source_url': source_url or 'default',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'starting'
        }
        streams.append(new_stream)
        save_telegram_streams(streams)

        # إنشاء سكريبت مؤقت للبث مع إعادة اتصال تلقائية
        temp_script = f"/tmp/tg_stream_{stream_id}.sh"
        with open(temp_script, 'w') as f:
            f.write(f"""#!/bin/bash
SOURCE="{source_url if source_url else 'http://soft24f.net/live/6872c3410e8cibopro/22bcpapc/237014.ts'}"
RTMP_URL="{stream_key}"

# حلقة لا نهائية لإعادة الاتصال التلقائي عند الانقطاع
while true; do
    echo "=========================================="
    echo "بدء البث: $(date)"
    echo "=========================================="

    ffmpeg -hide_banner -loglevel error \\
      -reconnect 1 -reconnect_streamed 1 -reconnect_at_eof 1 \\
      -reconnect_delay_max 10 \\
      -timeout 30000000 \\
      -fflags +genpts \\
      -analyzeduration 5000000 -probesize 5000000 \\
      -i "$SOURCE" \\
      -c:v libx264 -preset ultrafast -tune zerolatency \\
      -profile:v baseline -level 3.1 \\
      -vf "scale=854:480:force_original_aspect_ratio=decrease,pad=854:480:(ow-iw)/2:(oh-ih)/2,fps=25,drawtext=text='t.me/xl9rr':fontsize=20:fontcolor=white@0.85:shadowcolor=black@0.2:shadowx=1:shadowy=1:x=w-mod(t*120\\,w+tw):y=h-th-30" \\
      -b:v 1200k -maxrate 1500k -bufsize 2000k \\
      -g 50 -keyint_min 25 -sc_threshold 0 \\
      -pix_fmt yuv420p \\
      -c:a aac -b:a 64k -ar 44100 -ac 2 \\
      -af "aresample=async=1" \\
      -bsf:v h264_mp4toannexb \\
      -f flv "$RTMP_URL"

    EXIT_CODE=\$?
    echo "=========================================="
    echo "البث توقف: $(date) - كود الخروج: \$EXIT_CODE"
    echo "إعادة الاتصال خلال 10 ثوانٍ..."
    echo "=========================================="
    sleep 10
done
""")

        os.chmod(temp_script, 0o755)

        # إنشاء ملف تكوين Supervisor
        supervisor_conf_path = BASE_DIR / 'supervisor_logs' / f"{session_name}.conf"
        with open(supervisor_conf_path, 'w') as f:
            f.write(f"""[program:{session_name}]
command=/tmp/tg_stream_{stream_id}.sh
autostart=true
autorestart=true
stderr_logfile={BASE_DIR}/supervisor_logs/{session_name}_err.log
stdout_logfile={BASE_DIR}/supervisor_logs/{session_name}_out.log
""")
        
        # إخبار Supervisor بإعادة تحميل التكوينات
        try:
            subprocess.run(['supervisorctl', 'reread'], check=True)
            subprocess.run(['supervisorctl', 'update'], check=True)
        except Exception as e:
            print(f"Error updating supervisor: {e}")
            # قد لا يكون supervisorctl متاحاً أو يعمل بشكل صحيح في بيئة التجربة
            # في هذه الحالة، سنحاول تشغيل السكريبت مباشرة كبديل
            subprocess.Popen(
                ['tmux', 'new-session', '-d', '-s', session_name, temp_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

        import time
        time.sleep(4)

        # تحديث الحالة
        # محاولة التحقق من الحالة باستخدام supervisorctl إذا كان متاحاً
        try:
            status_result = subprocess.run(['supervisorctl', 'status', session_name], capture_output=True, text=True, check=True)
            if "RUNNING" in status_result.stdout:
                is_running = True
            else:
                is_running = False
        except:
            # في حالة عدم توفر supervisorctl، نعود لاستخدام tmux للتحقق
            is_running = get_stream_status(session_name)

        if is_running:
            for stream in streams:
                if stream['id'] == stream_id:
                    stream['status'] = 'running'
            save_telegram_streams(streams)
            return jsonify({'success': True, 'message': 'تم بدء البث إلى تليجرام بنجاح ✅', 'stream_id': stream_id})
        else:
            streams = [s for s in streams if s['id'] != stream_id]
            save_telegram_streams(streams)
            return jsonify({'success': False, 'error': 'فشل بدء البث'}), 500

    except Exception as e:
        try:
            # حذف ملف التكوين إذا تم إنشاؤه
            if session_name:
                supervisor_conf_path = BASE_DIR / 'supervisor_logs' / f"{session_name}.conf"
                if supervisor_conf_path.exists():
                    supervisor_conf_path.unlink()
        except:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/telegram/stream/stop/<stream_id>', methods=['POST'])
def api_telegram_stop_stream(stream_id):
    """إيقاف بث تليجرام معين"""
    try:
        streams = load_telegram_streams()
        stream = next((s for s in streams if s['id'] == stream_id), None)

        if not stream:
            return jsonify({'success': False, 'error': 'البث غير موجود'}), 404

        try:
            # محاولة الإيقاف باستخدام supervisorctl
            subprocess.run(['supervisorctl', 'stop', stream['session_name']], check=True)
        except:
            # في حالة الفشل، نعود لاستخدام tmux
            subprocess.run(['tmux', 'kill-session', '-t', stream['session_name']], check=False)


        import time
        time.sleep(1)

        stream['status'] = 'stopped'
        save_telegram_streams(streams)

        return jsonify({'success': True, 'message': 'تم إيقاف البث'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/telegram/stream/delete/<stream_id>', methods=['DELETE'])
def api_telegram_delete_stream(stream_id):
    """حذف بث من القائمة"""
    try:
        streams = load_telegram_streams()
        stream = next((s for s in streams if s['id'] == stream_id), None)

        if not stream:
            return jsonify({'success': False, 'error': 'البث غير موجود'}), 404

        try:
            # محاولة الإيقاف باستخدام supervisorctl
            subprocess.run(['supervisorctl', 'stop', stream['session_name']], check=True)
            # حذف ملف تكوين Supervisor
            supervisor_conf_path = BASE_DIR / 'supervisor_logs' / f"{stream['session_name']}.conf"
            if supervisor_conf_path.exists():
                subprocess.run(['supervisorctl', 'remove', stream['session_name']], check=False) # إخبار supervisor بإزالة البرنامج
                supervisor_conf_path.unlink()

            # إعادة تحميل Supervisor
            subprocess.run(['supervisorctl', 'reread'], check=False)
            subprocess.run(['supervisorctl', 'update'], check=False)

        except:
            # في حالة الفشل، نعود لاستخدام tmux
            if stream['status'] == 'running':
                subprocess.run(['tmux', 'kill-session', '-t', stream['session_name']], check=False)

        streams = [s for s in streams if s['id'] != stream_id]
        save_telegram_streams(streams)

        return jsonify({'success': True, 'message': 'تم حذف البث'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/telegram/stream/logs/<stream_id>')
def api_telegram_stream_logs(stream_id):
    """الحصول على سجلات بث معين"""
    try:
        streams = load_telegram_streams()
        stream = next((s for s in streams if s['id'] == stream_id), None)

        if not stream:
            return jsonify({'error': 'البث غير موجود'}), 404

        try:
            # محاولة الحصول على السجلات من supervisor
            log_file_path = BASE_DIR / 'supervisor_logs' / f'{stream["session_name"]}_out.log'
            if log_file_path.exists():
                with open(log_file_path, 'r') as f:
                    logs = f.read().splitlines()
                return jsonify({'logs': logs[-50:]}) # آخر 50 سطر
            else:
                 # في حالة عدم وجود سجلات supervisor، نعود لسجلات tmux
                result = subprocess.run(
                    ['tmux', 'capture-pane', '-t', stream['session_name'], '-p', '-S', '-50'],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode == 0:
                    logs = result.stdout.split('\n')
                    return jsonify({'logs': logs})
        except:
            pass

        return jsonify({'logs': ['لا توجد سجلات متاحة']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    LOGS_DIR.mkdir(exist_ok=True)
    supervisor_log_dir = BASE_DIR / 'supervisor_logs'
    supervisor_log_dir.mkdir(exist_ok=True)

    app.run(host='0.0.0.0', port=5000, debug=False)
