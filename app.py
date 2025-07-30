from flask import Flask, request, jsonify
import base64
import requests
import re
import fitz  # PyMuPDF

app = Flask(__name__)

def extract_part_number_from_text(text):
    try:
        match = re.search(r'料品號\s*[:：]?\s*\n?\s*(\S+)', text)
        return match.group(1) if match else None
    except Exception as e:
        return f"[Regex error: {str(e)}]"

def ocr_space_api_base64(file_stream, engine=2):
    try:
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
        response.raise_for_status()
        result = response.json()
        return result.get('ParsedResults', [{}])[0].get('ParsedText', '')
    except Exception as e:
        return f"[OCR API error: {str(e)}]"

def extract_text_from_pdf(file_stream):
    try:
        file_stream.seek(0)
        doc = fitz.open(stream=file_stream.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    except Exception as e:
        return f"[PDF parsing error: {str(e)}]"

@app.route('/extract-text', methods=['POST'])
def extract_text():
    try:
        files = request.files.getlist('file') or request.files.getlist('files') or request.files.getlist('files[]')
        if not files:
            return jsonify({'error': 'No files uploaded'}), 400

        results = []

        for file in files:
            if not file or file.filename == '':
                continue

            filename = file.filename
            part_number = None
            raw_text = ""

            try:
                if filename.startswith("C"):
                    raw_text = ocr_space_api_base64(file.stream)
                    extracted = extract_part_number_from_text(raw_text)
                    part_number = f"料品號：{extracted}" if extracted else "[No part number found]"

                elif filename.startswith("TW-TFDA"):
                    raw_text = extract_text_from_pdf(file.stream)
                    part_number = raw_text  # 直接複製 raw_text 到 part_number

                else:
                    raw_text = "[Unsupported filename format]"
                    part_number = "[Unsupported filename format]"

                results.append({
                    'filename': filename,
                    'part_number': part_number,
                    'raw_text': raw_text
                })

            except Exception as e:
                results.append({
                    'filename': filename,
                    'error': str(e)
                })

        return jsonify(results)

    except Exception as e:
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
