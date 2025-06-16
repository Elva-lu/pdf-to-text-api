from flask import Flask, request, jsonify
import fitz  # PyMuPDF
import os
import tempfile
import logging

app = Flask(__name__)

# 配置日誌
logging.basicConfig(level=logging.DEBUG)

@app.route('/extract-text', methods=['POST'])
def extract_text():
    logging.debug("Received request for /extract-text")

    # 同時支援 'files' 和 'files[]'
    files = request.files.getlist('files') or request.files.getlist('files[]')
    if not files:
        logging.error("No files uploaded")
        return jsonify({'error': 'No files uploaded'}), 400

    combined_text = ""

    for file in files:
        if file.filename == '':
            logging.warning("Empty filename encountered, skipping")
            continue

        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
                temp_path = temp_file.name
                file.save(temp_path)
                logging.debug("File saved to temporary path: %s", temp_path)

            logging.debug("Opening file with fitz")
            doc = fitz.open(temp_path)
            for page in doc:
                combined_text += page.get_text()
            doc.close()
            logging.debug("PDF processed successfully")
        except Exception as e:
            logging.error("Error processing PDF %s: %s", file.filename, str(e))
            combined_text += f"\n[Error processing {file.filename}: {str(e)}]\n"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                logging.debug("Temporary file removed")

    return jsonify({'text': combined_text})

if __name__ == '__main__':
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
