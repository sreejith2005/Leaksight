"""
Unit tests for Tool A extraction pipeline.
All tests are pure unit tests - no database, no file system beyond fixtures.
"""
import pytest
import os
import tempfile


class TestBaseExtractor:
    def test_normalized_line_item_defaults(self):
        from backend.app.tools.contract_structuring.extractors.base_extractor import NormalizedLineItem
        item = NormalizedLineItem(
            item_description="Steel Pipe",
            unit_raw="Nos",
            unit_price=850.0,
            item_confidence=0.9,
            price_confidence=0.95,
            unit_confidence=1.0,
        )
        assert item.currency == "INR"
        assert item.version_number == 1
        assert item.needs_review is False

    def test_null_price_is_allowed(self):
        from backend.app.tools.contract_structuring.extractors.base_extractor import NormalizedLineItem
        item = NormalizedLineItem(
            item_description="Unknown Item",
            unit_raw=None,
            unit_price=None,
            item_confidence=0.4,
            price_confidence=0.0,
            unit_confidence=0.0,
            needs_review=True,
        )
        assert item.unit_price is None
        assert item.needs_review is True


class TestTableNormalizer:
    def test_column_role_mapping_exact(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _map_column_roles
        roles = _map_column_roles(['Item', 'Unit', 'Rate', 'Currency'])
        assert roles['Item'] == 'ITEM_DESCRIPTION'
        assert roles['Unit'] == 'UNIT'
        assert roles['Rate'] == 'UNIT_PRICE'
        assert roles['Currency'] == 'CURRENCY'

    def test_column_role_mapping_fuzzy(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _map_column_roles
        roles = _map_column_roles(['Description', 'UOM', 'Unit Price'])
        assert roles['Description'] == 'ITEM_DESCRIPTION'
        assert roles['UOM'] == 'UNIT'
        assert roles['Unit Price'] == 'UNIT_PRICE'

    def test_unknown_columns_flagged(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _map_column_roles
        roles = _map_column_roles(['Column_XYZ_Unknown'])
        assert roles['Column_XYZ_Unknown'] == 'UNKNOWN'

    def test_parse_numeric_valid(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _parse_numeric
        val, conf = _parse_numeric("1,250.00")
        assert val == 1250.0
        assert conf > 0.9

    def test_parse_numeric_with_currency_symbol(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _parse_numeric
        val, conf = _parse_numeric("Rs. 850")
        assert val == 850.0

    def test_parse_numeric_zero_returns_none(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _parse_numeric
        val, conf = _parse_numeric("0")
        assert val is None

    def test_parse_numeric_empty_returns_none(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _parse_numeric
        val, conf = _parse_numeric("")
        assert val is None
        assert conf == 0.0

    def test_unit_numeric_guard_demotes_fuzzy_unit_column(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _map_column_roles

        rows = [
            {'Item': 'Cloud Hosting Services', 'Unit X': '2025', 'Rate': '6976.09'},
            {'Item': 'Managed Support', 'Unit X': '2,025', 'Rate': '3220.00'},
            {'Item': 'Security Audit', 'Unit X': '2024', 'Rate': '1100'},
        ]
        roles = _map_column_roles(['Item', 'Unit X', 'Rate'], rows)
        assert roles['Unit X'] == 'UNKNOWN'

    def test_unit_numeric_guard_skips_exact_keyword_unit_header(self):
        from backend.app.tools.contract_structuring.extractors.table_normalizer import _map_column_roles

        rows = [
            {'Item': 'Cloud Hosting Services', 'unit': '2025', 'Rate': '6976.09'},
            {'Item': 'Managed Support', 'unit': '2,025', 'Rate': '3220.00'},
            {'Item': 'Security Audit', 'unit': '2024', 'Rate': '1100'},
        ]
        roles = _map_column_roles(['Item', 'unit', 'Rate'], rows)
        assert roles['unit'] == 'UNIT'

    def test_contract_id_header_is_preserved_in_normalized_items(self):
        from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
        from backend.app.tools.contract_structuring.extractors.table_normalizer import normalize_tables

        table = RawTableResult(
            source_page=1,
            extraction_method='EXCEL_SHEET',
            raw_table_json=[
                {'Contract_ID': 'LS-CTR-001', 'Item': 'Steel Pipe', 'Unit': 'Nos', 'Rate': '850'},
                {'Contract_ID': 'LS-CTR-002', 'Item': 'Gate Valve', 'Unit': 'Nos', 'Rate': '3500'},
            ],
            table_confidence=0.95,
            column_count=4,
            row_count=2,
        )

        results = normalize_tables([table], stitched=False)

        assert [item.contract_id for item in results] == ['LS-CTR-001', 'LS-CTR-002']

    def test_detect_column_roles_prefers_contract_id_over_version_number(self):
        import pandas as pd
        from backend.app.tools.contract_structuring.extractors.table_normalizer import TableNormalizer

        df = pd.DataFrame(
            {
                'Contract_ID': ['LS-CTR-001', 'LS-CTR-002'],
                'Vendor_Name': ['TCS Ltd', 'Infosys'],
                'Item_Description': ['Data Processing', 'Consulting'],
                'Unit': ['GB', 'Hour'],
                'Unit_Price': [4122.47, 846.10],
                'Currency': ['USD', 'INR'],
                'Version_Number': [2, 1],
            }
        )

        roles = TableNormalizer().detect_column_roles(df)

        assert roles['Contract_ID'] == 'CONTRACT_ID'
        assert roles['Version_Number'] != 'CONTRACT_ID'


class TestMultiPageStitcher:
    def test_consecutive_same_columns_stitched(self):
        from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
        from backend.app.tools.contract_structuring.extractors.multi_page_stitcher import stitch_tables

        table1 = RawTableResult(
            source_page=1,
            extraction_method="CAMELOT_LATTICE",
            raw_table_json=[
                {"Item": "Header1", "Unit": "Header2", "Price": "Header3"},
                {"Item": "Steel Pipe", "Unit": "Nos", "Price": "850"},
            ],
            table_confidence=0.9,
            column_count=3,
            row_count=2,
        )
        table2 = RawTableResult(
            source_page=2,
            extraction_method="CAMELOT_LATTICE",
            raw_table_json=[
                {"Item": "Gate Valve", "Unit": "Nos", "Price": "3500"},
                {"Item": "Safety Helmet", "Unit": "Nos", "Price": "650"},
            ],
            table_confidence=0.9,
            column_count=3,
            row_count=2,
        )
        result = stitch_tables([table1, table2])
        assert result[1].is_continuation is True
        assert result[1].continued_from_index == 0

    def test_non_consecutive_pages_not_stitched(self):
        from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
        from backend.app.tools.contract_structuring.extractors.multi_page_stitcher import stitch_tables

        table1 = RawTableResult(
            source_page=1, extraction_method="CAMELOT_LATTICE",
            raw_table_json=[{"Item": "A", "Price": "100"}],
            table_confidence=0.9, column_count=2, row_count=1,
        )
        table2 = RawTableResult(
            source_page=5, extraction_method="CAMELOT_LATTICE",
            raw_table_json=[{"Item": "B", "Price": "200"}],
            table_confidence=0.9, column_count=2, row_count=1,
        )
        result = stitch_tables([table1, table2])
        assert result[1].is_continuation is False

    def test_different_column_count_not_stitched(self):
        from backend.app.tools.contract_structuring.extractors.base_extractor import RawTableResult
        from backend.app.tools.contract_structuring.extractors.multi_page_stitcher import stitch_tables

        table1 = RawTableResult(
            source_page=1, extraction_method="CAMELOT_LATTICE",
            raw_table_json=[{"Item": "A", "Unit": "Nos", "Price": "100"}],
            table_confidence=0.9, column_count=3, row_count=1,
        )
        table2 = RawTableResult(
            source_page=2, extraction_method="CAMELOT_LATTICE",
            raw_table_json=[{"Item": "B", "Price": "200"}],
            table_confidence=0.9, column_count=2, row_count=1,
        )
        result = stitch_tables([table1, table2])
        assert result[1].is_continuation is False


class TestClauseExtractor:
    def test_effective_date_extraction(self):
        from backend.app.tools.contract_structuring.extractors.clause_extractor import extract_clauses
        text = "This agreement is effective from 01 April 2024 and shall remain in force."
        clauses = extract_clauses(text)
        effective = [c for c in clauses if c.clause_type == 'EFFECTIVE_DATE']
        assert len(effective) >= 1
        assert effective[0].extracted_value is not None
        assert '2024' in effective[0].extracted_value

    def test_expiry_date_extraction(self):
        from backend.app.tools.contract_structuring.extractors.clause_extractor import extract_clauses
        text = "Contract valid until 31 March 2026."
        clauses = extract_clauses(text)
        expiry = [c for c in clauses if c.clause_type == 'EXPIRY_DATE']
        assert len(expiry) >= 1

    def test_amendment_ref_extraction(self):
        from backend.app.tools.contract_structuring.extractors.clause_extractor import extract_clauses
        text = "This is Amendment No. 3 to the Master Services Agreement."
        clauses = extract_clauses(text)
        amendment = [c for c in clauses if c.clause_type == 'AMENDMENT_REF']
        assert len(amendment) >= 1
        assert amendment[0].extracted_value == '3'

    def test_contract_ref_extraction(self):
        from backend.app.tools.contract_structuring.extractors.clause_extractor import extract_clauses
        text = "Contract No: CTR-2024-001 dated 1st April 2024"
        clauses = extract_clauses(text)
        refs = [c for c in clauses if c.clause_type == 'CONTRACT_REF']
        assert len(refs) >= 1

    def test_empty_text_returns_empty(self):
        from backend.app.tools.contract_structuring.extractors.clause_extractor import extract_clauses
        assert extract_clauses("") == []
        assert extract_clauses("   ") == []

    def test_low_confidence_sets_needs_review(self):
        from backend.app.tools.contract_structuring.extractors.clause_extractor import extract_clauses
        text = "effective from the date of signing as mutually agreed"
        clauses = extract_clauses(text)
        for c in clauses:
            if c.clause_type == 'EFFECTIVE_DATE' and c.extracted_value is None:
                assert c.needs_review is True


class TestExcelExtractor:
    def test_pricing_sheet_detected(self):
        import pandas as pd
        import tempfile
        from backend.app.tools.contract_structuring.extractors.excel_extractor import extract_tables_from_excel

        data = {
            'Item Description': ['Steel Pipe', 'Gate Valve'],
            'Unit': ['Nos', 'Nos'],
            'Unit Price': [850.0, 3500.0],
        }
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            path = f.name
        try:
            pd.DataFrame(data).to_excel(path, index=False)
            tables = extract_tables_from_excel(path)
            assert len(tables) >= 1
            assert tables[0].extraction_method == 'EXCEL_SHEET'
            assert tables[0].table_confidence > 0.5
        finally:
            os.unlink(path)

    def test_non_pricing_sheet_low_confidence(self):
        import pandas as pd
        import tempfile
        from backend.app.tools.contract_structuring.extractors.excel_extractor import extract_tables_from_excel

        data = {'Name': ['Alice', 'Bob'], 'Department': ['HR', 'IT']}
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            path = f.name
        try:
            pd.DataFrame(data).to_excel(path, index=False)
            tables = extract_tables_from_excel(path)
            assert all(t.table_confidence < 0.5 for t in tables)
        finally:
            os.unlink(path)

    def test_extract_structured_clauses_from_excel_columns(self):
        import pandas as pd
        import tempfile
        from backend.app.tools.contract_structuring.extractors.excel_extractor import ExcelExtractor

        data = {
            'Contract_ID': ['LS-CTR-001', 'LS-CTR-001'],
            'Vendor_Name': ['TCS Ltd', 'TCS Ltd'],
            'Effective_Start_Date': ['2024-02-29', '2024-02-29'],
            'Effective_End_Date': ['2025-04-09', '2025-04-09'],
            'Item_Description': ['Data Processing Services', 'Cloud Support'],
            'Unit': ['GB', 'Hour'],
            'Unit_Price': [4122.47, 846.10],
            'Currency': ['USD', 'USD'],
            'Version_Number': [2, 2],
        }
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            path = f.name
        try:
            pd.DataFrame(data).to_excel(path, index=False)
            result = ExcelExtractor().extract(path)
            clauses = {clause.clause_type: clause.extracted_value for clause in result.clauses}

            assert clauses['VENDOR_NAME'] == 'TCS Ltd'
            assert clauses['EFFECTIVE_DATE'] == '2024-02-29'
            assert clauses['EXPIRY_DATE'] == '2025-04-09'
            assert clauses['CONTRACT_REF'] == 'LS-CTR-001'
        finally:
            os.unlink(path)


class TestPdfExtractor:
    def test_scanned_pdf_falls_back_to_page_ocr(self, monkeypatch, tmp_path):
        from backend.app.tools.contract_structuring.extractors import pdf_extractor

        document_path = tmp_path / 'scan.pdf'
        document_path.write_bytes(b'%PDF-1.4 test')

        monkeypatch.setattr(pdf_extractor, '_get_pdf_page_count', lambda _: 1)
        monkeypatch.setattr(pdf_extractor, '_try_camelot_lattice', lambda *args, **kwargs: [])
        monkeypatch.setattr(pdf_extractor, '_try_camelot_stream', lambda *args, **kwargs: [])
        monkeypatch.setattr(pdf_extractor, '_try_pdfplumber', lambda *args, **kwargs: [])
        monkeypatch.setattr(
            pdf_extractor,
            '_process_page_with_timeout',
            lambda *args, **kwargs: {
                'status': 'success',
                'text': 'Contract LS-CTR-001',
                'rows': [{'Contract ID': 'LS-CTR-001', 'Item': 'Steel Pipe', 'Rate': '850'}],
                'confidences': [0.91, 0.93],
            },
        )

        tables = pdf_extractor.extract_tables_from_pdf(str(document_path))

        assert len(tables) == 1
        assert tables[0].extraction_method == 'PADDLE_OCR'
        assert tables[0].raw_table_json[0]['Contract ID'] == 'LS-CTR-001'

    def test_scanned_pdf_timeout_skips_page_and_continues(self, monkeypatch, tmp_path):
        from backend.app.tools.contract_structuring.extractors import pdf_extractor

        document_path = tmp_path / 'scan.pdf'
        document_path.write_bytes(b'%PDF-1.4 test')

        responses = iter([
            {'status': 'timeout'},
            {
                'status': 'success',
                'text': 'Page 2',
                'rows': [{'Item': 'Gate Valve', 'Rate': '3500'}],
                'confidences': [0.88],
            },
        ])

        monkeypatch.setattr(pdf_extractor, '_get_pdf_page_count', lambda _: 2)
        monkeypatch.setattr(pdf_extractor, '_try_camelot_lattice', lambda *args, **kwargs: [])
        monkeypatch.setattr(pdf_extractor, '_try_camelot_stream', lambda *args, **kwargs: [])
        monkeypatch.setattr(pdf_extractor, '_try_pdfplumber', lambda *args, **kwargs: [])
        monkeypatch.setattr(
            pdf_extractor,
            '_process_page_with_timeout',
            lambda *args, **kwargs: next(responses),
        )

        tables = pdf_extractor.extract_tables_from_pdf(str(document_path))

        assert len(tables) == 1
        assert tables[0].source_page == 2
