"""PDF tables: recover the columns that layout extraction leaves behind."""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from stock_predict_mailer.private_knowledge.parsing import parse, pdf_blocks

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    HAVE_PYPDF = True
except ImportError:  # knowledge extra not installed
    HAVE_PYPDF = False

# 一页里同时有两栏正文和一张表：只有表格那几行能被结构化，正文必须留在段落里。
LAYOUT = """
三、资产质量                          五、募集资金使用情况

截至报告期末，本行不良率（不良贷款率口径）为             2026 年 6 月，本行完成向特定对象发行股票

 项目              本期        上年同期      同比变动

 营业收入          1,236.45    1,197.98      3.21%

 净利润            402.18      394.91        1.84%
"""


def pdf(rows, *, font='Helvetica', columns=(30, 150, 260)):
    """A minimal one-page PDF with text placed at column positions."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=300)
    font_object = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                    NameObject('/BaseFont'): NameObject('/' + font)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font_object)})})
    body = ['BT /F1 10 Tf']
    for index, row in enumerate(rows):
        for column, text in zip(columns, row, strict=False):
            body.append(f'1 0 0 1 {column} {260 - index * 18} Tm ({text}) Tj')
    body.append('ET')
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(body).encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    raw = io.BytesIO()
    writer.write(raw)
    return raw.getvalue()


class LayoutBlockTests(unittest.TestCase):
    def test_a_table_is_split_while_two_column_prose_stays_a_paragraph(self):
        blocks = pdf_blocks(LAYOUT)
        self.assertEqual([block["kind"] for block in blocks], ["prose", "table"])
        # 两栏正文每行也切出两个单元格，但内容是长句：判据是单元格形状，不是列数。
        self.assertEqual(blocks[0]["lines"][0], "三、资产质量  五、募集资金使用情况")
        self.assertTrue(blocks[0]["lines"][1].startswith("截至报告期末，本行不良率"))
        self.assertEqual(blocks[1]["rows"][0], ["项目", "本期", "上年同期", "同比变动"])
        self.assertEqual(blocks[1]["rows"][1], ["营业收入", "1,236.45", "1,197.98", "3.21%"])

    def test_thousands_separators_do_not_disqualify_a_numeric_column(self):
        blocks = pdf_blocks(" 营业收入   1,236.45   3.21%\n 净利润   402.18   1.84%\n")
        self.assertEqual([block["kind"] for block in blocks], ["table"])

    def test_a_single_row_is_not_a_table(self):
        blocks = pdf_blocks("证券代码：600000.SH      披露日期：2026-10-28\n")
        self.assertEqual([block["kind"] for block in blocks], ["prose"])

    def test_ragged_cell_counts_do_not_become_a_table(self):
        # 列数对不齐时退回段落，但不把两行硬拼进同一张表：错位的列比段落更糟。
        blocks = pdf_blocks(" 项目        本期        同比\n 营业收入     1,236.45\n")
        self.assertTrue(blocks and all(block["kind"] == "prose" for block in blocks))


@unittest.skipUnless(HAVE_PYPDF, 'knowledge extra required')
class PdfTableParseTests(unittest.TestCase):
    def test_none_from_pdf_extractor_keeps_ocr_review_error(self):
        raw = pdf([('Item', 'Value', 'Change')])
        with patch("pypdf._page.PageObject.extract_text", return_value=None):
            with self.assertRaisesRegex(Exception, "OCR"):
                parse("scan.pdf", raw)

    def test_rows_become_fields_with_page_and_row_locations(self):
        raw = pdf([('Item', 'Value', 'Change'), ('Revenue', '12.5', '3.1%'), ('Cost', '7.4', '-1.2%')])
        self.assertTrue(PdfReader(io.BytesIO(raw)).pages[0].extract_text(extraction_mode='layout'))
        parsed = parse('t.pdf', raw)
        rows = [piece for piece in parsed['pieces'] if 'fields' in piece and piece['fields']]
        self.assertEqual([piece['fields'] for piece in rows],
                         [{'Item': 'Revenue', 'Value': '12.5', 'Change': '3.1%'},
                          {'Item': 'Cost', 'Value': '7.4', 'Change': '-1.2%'}])
        self.assertEqual(rows[0]['location'], {'page': 1, 'table_block': 1, 'row': 1})
        self.assertEqual(rows[0]['original'], 'Item: Revenue；Value: 12.5；Change: 3.1%')
        self.assertTrue(any('列边界' in warning for warning in parsed['warnings']))

    def test_repeated_header_is_reported_instead_of_guessed(self):
        raw = pdf([('Value', 'Value', 'Change'), ('12.5', '13.0', '3.1%')])
        parsed = parse('t.pdf', raw)
        self.assertTrue(any('表头为空或重复' in warning for warning in parsed['warnings']))
        # 表头不可信时整块降级成段落：宁可少结构化，也不把错位的列当成字段。
        self.assertTrue(all(not piece['fields'] for piece in parsed['pieces']))

    def test_a_page_without_text_still_asks_for_ocr(self):
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        raw = io.BytesIO()
        writer.write(raw)
        with self.assertRaises(Exception) as caught:
            parse('scan.pdf', raw.getvalue())
        self.assertIn('OCR', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
