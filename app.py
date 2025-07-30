from flask import Flask, request, jsonify
import base64
import requests
import re

app = Flask(__name__)  # ✅ 必須在最前面定義

def extract_part_numbers(text):
    pattern = r'\b[A-Za-z\s]+?\(\d+\)'
    return re.findall(pattern, text)

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
    part_numbers = []

    for file in files:
        if not file or file.filename == '':
            continue

        try:
            file.stream.seek(0)
            filename = file.filename

            # 判斷是否需要 OCR
            if filename.startswith("C"):
                text = ocr_space_api_base64(file.stream)
                part_numbers += extract_part_numbers(text)
            elif filename.startswith("TW-TFDA"):
                text = "(這裡放 PDF 轉文字的邏輯)"
            else:
                text = "(未知檔名格式，可選擇預設處理方式)"

            combined_text += f"\n--- {filename} ---\n{text}\n"

        except Exception as e:
            combined_text += f"\n[Error processing {file.filename}: {str(e)}]\n"

    return jsonify({
        'text': combined_text,
        'part_numbers': list(set(part_numbers))
    })

if __name__ == '__main__':
    import os
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
