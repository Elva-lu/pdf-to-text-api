from flask import Flask, request, jsonify
import base64
import requests
import re

app = Flask(__name__)

def extract_part_number_from_text(text):
    match = re.search(r'料品號\s*[:：]?\s*\n?\s*(\S+)', text)
    return match.group(1) if match else None

def ocr_space_api_base64(file_stream, engine=2):
    file_stream.seek(0)
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

            if filename.startswith("C"):
                file.stream.seek(0)
                raw_text = ocr_space_api_base64(file.stream)
                extracted = extract_part_number_from_text(raw_text)
                if extracted:
                    part_number = f"料品號：{extracted}"

            elif filename.startswith("TW-TFDA"):
                part_number = None

            results.append({
                'filename': filename,
                'part_number': part_number
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
