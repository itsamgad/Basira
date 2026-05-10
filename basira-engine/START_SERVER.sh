#!/bin/bash
echo "================================================"
echo "  Basira Smart Preprocessor — Python Backend"
echo "================================================"
echo ""
echo "Installing dependencies..."
pip install flask pandas numpy scikit-learn scipy openpyxl xlrd -q
echo ""
echo "Starting server on http://localhost:5050"
echo "Open basira_preprocessor.html in your browser"
echo "================================================"
python3 basira_app.py
