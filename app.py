from flask import Flask, request, jsonify
import os
import tempfile
import requests

app = Flask(__name__)

def ocr_space_api(file_path):
    with open(file_path, 'rb') as f:
        response = requests.post(
            'https://api.ocr.space/parse/image',
            files={'file': f},
            data={
                'apikey': 'K85762331988957',  # ← 填入你的 API Key
                'language': 'cht',        # 使用繁體中文 OCR
                'isOverlayRequired': False,
                'OCREngine': 2
            },
            timeout=30  # 最多等待 30 秒，避免 Make 超時
        )
    result = response.json()
    return result.get('ParsedResults', [{}])[0].get('ParsedText', '')

@app.route('/extract-text', methods=['POST'])
def extract_text():
    file = request.files.get('file') or request.files.get('files') or request.files.get('files[]')
    if not file or file.filename == '':
        return jsonify({'error': 'No file uploaded'}), 400

    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_path = temp_file.name
            file.save(temp_path)

        text = ocr_space_api(temp_path)
    except Exception as e:
        return jsonify({'error': f'OCR failed: {str(e)}'}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return jsonify({'text': text})

if __name__ == '__main__':
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
