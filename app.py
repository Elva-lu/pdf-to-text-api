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
    if 'file' not in request.files:
        logging.error("No file part in request")
        return jsonify({'error': 'No file part in the request'}), 400

    file = request.files['file']
    if file.filename == '':
        logging.error("No selected file")
        return jsonify({'error': 'No selected file'}), 400

    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_path = temp_file.name
            file.save(temp_path)
            logging.debug("File saved to temporary path: %s", temp_path)

        logging.debug("Opening file with fitz")
        doc = fitz.open(temp_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        logging.debug("PDF processed successfully")
    except Exception as e:
        logging.error("Error processing PDF: %s", str(e))
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            logging.debug("Temporary file removed")

    return jsonify({'text': text})

if __name__ == '__main__':
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
