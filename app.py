from flask import Flask, request, jsonify
import base64
import requests
import re

app = Flask(__name__)

def extract_part_number_from_text(text):
    # 支援「料品號」在下一行的情況
    match = re.search(r'料品號\s*[:：]?\s*\n?\s*(\S+)', text)
    return match.group(1) if match else None

def ocr_space_api_base64(file_stream, engine=2):
    file_stream.seek(0)  # 確保從頭讀取
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

    results = []

    for file in files:
        if not file or file.filename == '':
            continue

        try:
            filename = file.filename
            part_number = None
            raw_text = ""

            if filename.startswith("C"):
                file.stream.seek(0)
                raw_text = ocr_space_api_base64(file.stream)
                print(f"OCR text for {filename}:\n{raw_text}")  # debug log
                part_number = extract_part_number_from_text(raw_text)

            elif filename.startswith("TW-TFDA"):
                raw_text = "(PDF 轉文字邏輯尚未實作)"
                part_number = None

            else:
                raw_text = "(未知檔名格式)"
                part_number = None

            results.append({
                'filename': filename,
                'part_number': part_number,
                'raw_text': raw_text[:500]  # 可選：只回傳前 500 字避免太長
            })

        except Exception as e:
            results.append({
                'filename': file.filename,
                'error': str(e)
            })

    return jsonify(results)

if __name__ == '__main__':
    import os
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
