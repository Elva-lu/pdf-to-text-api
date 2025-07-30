from flask import Flask, request, jsonify
import base64
import requests

app = Flask(__name__)

def ocr_space_api_base64(file_stream, engine=2):
    base64_data = base64.b64encode(file_stream.read()).decode()
    response = requests.post(
        'https://api.ocr.space/parse/image',
        data={
            'apikey': 'K85762331988957',
            'language': 'cht',
            'isOverlayRequired': False,
            'OCREngine': engine,
            'base64Image': f'data:application/pdf;base64,{base64_data}'
        },
        timeout=30
    )
    result = response.json()
    return result.get('ParsedResults', [{}])[0].get('ParsedText', '')

@app.route('/extract-text', methods=['POST'])
def extract_text():
    files = request.files.getlist('file') or request.files.getlist('files') or request.files.getlist('files[]')
    if not files:
        return jsonify({'error': 'No files uploaded'}), 400

    combined_text = ""

    for file in files:
        if not file or file.filename == '':
            continue

        try:
            file.stream.seek(0)  # 確保讀取從頭開始
            text = ocr_space_api_base64(file.stream)
            combined_text += f"\n--- {file.filename} ---\n{text}\n"
        except Exception as e:
            combined_text += f"\n[Error processing {file.filename}: {str(e)}]\n"

    return jsonify({'text': combined_text})

if __name__ == '__main__':
    import os
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
