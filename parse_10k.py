
from codecs import decode
import html
import os
import re
from time import time
import unicodedata

from bs4 import BeautifulSoup, Tag
from edgar import write_content, find_mda_from_text
import imgkit
from tqdm import tqdm


def extract_html_file(raw_html_text, file_name, fix_UUEncode=False):
    doc_list = raw_html_text.split('<DOCUMENT>')
    
    if file_name == "10-K":
        doc_10K = doc_list[1]
        if re.search(r'\n<TYPE>10-K', doc_10K):
            return doc_10K
        else:
            raise RuntimeError("Not find 10-K in the beginning of submission file")
    
    for doc in doc_list:
        if re.search(rf'\n<FILENAME>{file_name}', doc):
            if fix_UUEncode:
                doc = re.search(r'(begin .*end\n)', doc, flags=re.DOTALL)
                try:
                    binary_doc = doc.group(1).encode('raw_unicode_escape') # type: ignore
                    return decode(binary_doc, 'uu')
                except:
                    raise RuntimeError(f"UUEncode error in {file_name}")
            return doc
    raise RuntimeError(f"Not find file {file_name} in the submission file")


# def extract_html_tables_images(html_text, raw_html_text):
#     soup = BeautifulSoup(html_text, 'lxml')
    
#     table_tags = soup.find_all(name='table')
#     table_idx = 0
#     tables_dict = {}
#     for tag in table_tags:
#         if not isinstance(tag, Tag):
#             continue
#         table_style = tag.attrs.get('style', '')
#         if 'border:0' in table_style:
#             continue
#         table_idx += 1
#         table_id = f"table_{table_idx}"
#         tables_dict[table_id] = str(tag)

#         new_tag = soup.new_tag('i')
#         new_tag.string = f"\n--- TABLE_PLACEHOLDER: {table_id} ---\n"
#         tag.replace_with(new_tag)

#     image_tags = soup.find_all(name='img')
#     images_dict = {}
#     for tag in image_tags:
#         if not isinstance(tag, Tag):
#             continue
#         image_src = tag.attrs.get('src', '')
#         image_id = f"image_{image_src}"
#         if image_data := extract_html_file(raw_html_text, image_src, True):
#             images_dict[image_id] = image_data

#         new_tag = soup.new_tag('i')
#         new_tag.string = f"\n--- IMAGE_PLACEHOLDER: {image_id} ---\n"
#         tag.replace_with(new_tag)
    
#     return str(soup), tables_dict, images_dict


def extract_html_tables_images(html_text, raw_html_text):
    table_items = re.findall(r'<table.*?</table>', html_text, flags=re.DOTALL)
    print('Find', len(table_items), "raw tables")
    table_idx = 0
    tables_dict = {}
    for item in table_items:
        # table_style = re.search(r'style="(.*?)"', item, flags=re.DOTALL)
        # if not table_style or not 'border:0' in table_style.group(1):
        #     continue
        if not re.search(r'#cceeff', item, re.IGNORECASE) and len(re.findall(r'</tr>', item)) < 10:
            continue
        table_idx += 1
        table_id = f"table_{table_idx}"
        tables_dict[table_id] = item
        html_text = html_text.replace(item, f"<i>\n--- TABLE_PLACEHOLDER: {table_id} ---\n</i>")
    
    image_items = re.findall(r'<img.*?>', html_text, flags=re.DOTALL)
    images_dict = {}
    for item in image_items:
        image_src = re.search(r'src="(.*?)"', item, flags=re.DOTALL)
        if image_src:
            image_src = image_src.group(1)
        else:
            raise RuntimeError("Not find image file name")
        image_id = f"image_{image_src}"
        if image_data := extract_html_file(raw_html_text, image_src, True):
            images_dict[image_id] = image_data
        html_text = html_text.replace(item, f"<i>\n--- IMAGE_PLACEHOLDER: {image_id} ---\n</i>")

    return html_text, tables_dict, images_dict


def normalize_html(html_text, raw_html_text):
    # Delete ix header, page number and header (TOC link)
    ix_pattern = r'<ix:header>.*?</ix:header>'
    pn_pattern = r'<div (style="display:table-cell;vertical-align:bottom;width:100%;|class="footer).*?</div>'
    ph_pattern = r'<a href="#TOC".*?</a>'
    html_text = re.sub(ix_pattern, "", html_text, flags=re.DOTALL | re.IGNORECASE)
    # html_text = re.sub(pn_pattern, "", html_text, flags=re.DOTALL)
    html_text = re.sub(ph_pattern, "", html_text, flags=re.DOTALL | re.IGNORECASE)

    # Replace bold nodes with *
    bold_previous_pattern = r'<strong.*?>|<b.*?>'
    bold_following_pattern  = r'</strong>|</b>'
    html_text = re.sub(bold_previous_pattern, r"** ", html_text)
    html_text = re.sub(bold_following_pattern, r" **", html_text)

    # Extract html table
    html_text, tables_dict, images_dict = extract_html_tables_images(html_text, raw_html_text)
    print("Save {} tables".format(len(tables_dict)))
    print("Save {} image".format(len(images_dict)))

    # Replace special characters (implemented by unicodedata library)
    # html_text = re.sub(r'(&#160;|\xa0)+', " ", html_text)
    # html_text = re.sub(r'(&#8217;|’)', "'", html_text)
    # html_text = re.sub(r'(\u200b)+', "\n", html_text)

    return html_text, tables_dict, images_dict


def process_inline_text(soup):
    for tag in soup.find_all(name=['p', 'b', 'span']):
        if not isinstance(tag, Tag):
            continue
        tag_style = tag.attrs.get('style', '')
        if isinstance(tag_style, str) and re.search(r'text-align: ?center', tag_style, re.IGNORECASE):
            if isinstance(tag.string, str) and re.match(r'[0-9ivIV]+', tag.string.strip()):
                tag.string = ''
                continue
        if isinstance(tag_style, str) and re.search(r'font-weight: ?bold', tag_style, re.IGNORECASE):
            tag.string = '\n** ' + tag.get_text() + ' ** '

    # for tag in soup.find_all(name=['span', 'em', 'sup', 'sub', 'strong', 'b', 'i', 'a', 'td', re.compile('^ix:')]):
    for tag in soup.find_all(name=['span', 'em', 'sup', 'sub', 'i', 'a', 'td', re.compile('^ix:')]):
        if not isinstance(tag, Tag):
            continue
        tag.replace_with(tag.get_text("")) # type: ignore

    for tag in soup.find_all(name=['p', 'tr']):
        if not isinstance(tag, Tag):
            continue
        if all(not isinstance(c, Tag) for c in tag.children):
            try:
                if tag.name == 'tr':
                    tag.string = '\t\t' + tag.get_text().replace("\n", "")
                    continue
                else:
                    p_style = tag.attrs.get('style', '')
                    p_indent = re.search(r'text-indent: ?([0-9.]*?)pt', str(p_style), flags=re.IGNORECASE)
                    if p_indent and float(p_indent.group(1)) > 0:
                        tag.string = '\t\t' + tag.get_text().replace("\n", "")
                    else:
                        tag.string = '\n' + tag.get_text().replace("\n", "")
            except:
                tag.string = tag.get_text().replace("\n", "")
    
    return soup


def process_page_break(soup):
    for tag in soup.find_all(name=['div', 'hr']):
        if not isinstance(tag, Tag):
            continue

        tag_style = tag.attrs.get('style', '')
        if isinstance(tag_style, str) and re.search(r'page-breaks?-after:\s?always', tag_style, flags=re.IGNORECASE):
            tag.string = '--- PAGE BREAK ----' + tag.get_text()

    return soup


def is_plain_paragraph(line_text):
    if line_text.find('**') != -1 or line_text.find('---') != -1:
        return False
    if re.search(r'^[A-Z]+$', line_text):
        return False
    if re.search(r'^(\b[A-Z]{2,}\b[A-Z]{2,}\b|Item)', line_text):
        return False
    if line_text.strip().istitle() or line_text.strip().isupper():
        return False
    return True


def concat_text(content_text):
    content_text = re.sub(r'\s+(--- PAGE BREAK ----)\s+([a-z])', r' \2', content_text)
    content_text = re.sub(r'--- PAGE BREAK ----', r'\n', content_text)

    content_text = re.sub(r'^(\*{4,}|\*\* *\*\*)', '**', content_text, flags=re.MULTILINE)
    content_text = re.sub(r'(\*{4,}|\*\* *\*\*)\s+$', '**', content_text, flags=re.MULTILINE)
    content_text = re.sub(r'(\*{4,}|\s?\*\* *\*\*)\s?', '', content_text, flags=re.MULTILINE)
    content_text = re.sub(r'^(\*|\s)+$', '', content_text, flags=re.MULTILINE)

    content_text = re.sub(r' {2,}', ' ', content_text)
    content_text = re.sub(r'\)(\w)', r') \1', content_text)
    content_text = re.sub(r'(\w)\(', r'\1 (', content_text)

    content_text = re.sub(r'\n\s+\n', r'\n\n', content_text)
    content_text = re.sub(r'\n([a-z]+)', r' \1', content_text)
    content_text = re.sub(r'\n\n(\t\t[A-Z]+)', r'\n\1', content_text)

    new_lines = []
    old_lines = content_text.split('\n')
    for line_idx, line in enumerate(old_lines):
        if line_idx < 20 or line_idx > len(old_lines)-2:
            new_lines.append(line)
            continue
        if  line.strip() == '':
            previous_line = old_lines[line_idx-1]
            following_line = old_lines[line_idx+1]
            if is_plain_paragraph(previous_line) and is_plain_paragraph(following_line):
                continue
        new_lines.append(line)
    content_text = '\n'.join(new_lines)

    content_text = re.sub(r'\n+([ *]*Item|Part|ITEM|PART)', r'\n{3}\1', content_text)

    # content_text = re.sub(r'([^\n])(--- .*?PLACEHOLDER.*? ---)', r'\1\n\2', content_text, flags=re.MULTILINE)
    # content_text = re.sub(r'(--- .*?PLACEHOLDER.*? ---)([^\n])', r'\1\n\2', content_text, flags=re.MULTILINE)

    return content_text


def parse_html(input_file, output_file, overwrite=False, render_table_image=False):
    """Parses text from html with BeautifulSoup
    Args:
        input_file (str)
        output_file (str)
    """
    if not overwrite and os.path.exists(output_file):
        print("{} already exists. Skipping parse html...".format(output_file))
        return

    # Read raw html text
    print("Parsing html {}".format(input_file))
    with open(input_file, 'r', encoding='utf-8-sig') as fin:
        raw_content = fin.read()
    content = extract_html_file(raw_content, "10-K")
    content = html.unescape(content) # type: ignore
    content = content.replace('●', '>> ')
    content = unicodedata.normalize('NFKD', content).encode('ascii', 'ignore').decode('ascii')
    
    # Normalize html text
    t = time()
    content, tables_dict, images_dict = normalize_html(content, raw_content)
    print(f"→ HTML normalize: {time() - t:.3f}s")

    # Parse html with BeautifulSoup
    t = time()
    soup = BeautifulSoup(content, "lxml")
    soup = process_inline_text(soup)
    soup = process_page_break(soup)
    print(f"→ BS4 parse: {time() - t:.3f}s")

    t = time()
    content_text = soup.get_text("\n")
    content_text = concat_text(content_text)
    write_content(content_text, output_file)
    print(f"→ Text concat: {time() - t:.3f}s")

    t = time()
    if render_table_image:
        table_image_dir = input_file.replace('.txt', '')
        os.makedirs(table_image_dir, exist_ok=True)
        pbar_tables_dict = tqdm(tables_dict.items())
        for name, data in pbar_tables_dict:
            pbar_tables_dict.set_description("Rendering Tables")
            imgkit.from_string(data, os.path.join(table_image_dir, name + '.jpg'), options={'quality': 90, 'quiet': None})
        pbar_images_dict = tqdm(images_dict.items())
        for name, data in pbar_images_dict:
            pbar_images_dict.set_description("Rendering Images")
            with open(os.path.join(table_image_dir, name), 'wb') as f:
                f.write(data)
    print(f"→ Render tables and images: {time() - t:.3f}s")

    # Log message
    print("Write to {}".format(output_file))


def parse_mda(form_path, mda_path, overwrite=False):
    """Reads form and parses mda
    Args:
        form_path (str)
        mda_path (str)
    """
    if not overwrite and os.path.exists(mda_path):
        print("{} already exists.  Skipping parse mda...".format(mda_path))
        return
    # Read
    print("Parse MDA {}".format(form_path))
    with open(form_path, "r") as fin:
        text = fin.read()

    # Normalize text here
    text = normalize_text(text)

    # Parse MDA
    mda, end = find_mda_from_text(text)
    # Parse second time if first parse results in index
    if mda and len(mda.encode("utf-8")) < 1000:
        mda, _ = find_mda_from_text(text, start=end)

    if mda:
        print("Write MDA to {}".format(mda_path))
        write_content(mda, mda_path)
    else:
        print("Parse MDA failed {}".format(form_path))
        

def normalize_text(text):
    """Normalize Text"""
    text = unicodedata.normalize("NFKD", text)  # Normalize
    text = "\n".join(text.splitlines())  # Unicode break lines

    # Convert to upper
    # text = text.upper()  # Convert to upper

    # Take care of breaklines & whitespaces combinations due to beautifulsoup parsing
    text = re.sub(r"[ ]+\n", "\n", text)
    text = re.sub(r"\n[ ]+", "\n", text)
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"^(\s*)([A-Z])", "\2", text)

    # To find MDA section, reformat item headers
    text = text.replace("\n.\n", ".\n")  # Move Period to beginning

    text = re.sub(r"I\s?T\s?E\s?M", "ITEM", text)
    text = re.sub(r"I\s?t\s?e\s?m", "Item", text)
    text = re.sub(r"M\s?A\s?N\s?A\s?G\s?E\s?M\s?E\s?N\s?T", "MANAGEMENT", text)
    text = re.sub(r"M\s?a\s?n\s?a\s?g\s?e\s?m\s?e\s?n\s?t", "Management", text)

    text = re.sub(r"(?i)(Item\s*\d\.)\s+", r"\1 ", text)

    # text = text.replace("\nI\nTEM", "\nITEM")
    # text = text.replace("\nITEM\n", "\nITEM ")
    # text = text.replace("\nITEM  ", "\nITEM ")

    # text = text.replace("\nItem\n", "\nItem ")
    # text = text.replace("\nItem  ", "\nItem ")
    
    text = text.replace(":\n", ".\n")

    # Math symbols for clearer looks
    text = text.replace("$\n", "$")
    text = text.replace("\n%", "%")

    # Reformat
    # text = text.replace("\n", "\n\n")  # Reformat by additional breakline

    return text


if __name__ == "__main__":

    raw_files = [
        "test_data/example.form10k_0001558370-23-003469.txt",
        "test_data/example.form10k_0001477932-23-002105.txt",
        "test_data/example.form10k_0000842518-23-000016.txt",
        "test_data/example.form10k_0001558370-23-004037.txt"
    ]

    for raw_file in raw_files:
        time_start = time()
        parse_html(raw_file, re.sub("form10k", "form10k.parsed", raw_file), True, True)
        time_end = time()
        print(f"Time spent: {time_end-time_start:.2f}\n\n")
    # parse_mda("test_data/example.form10k.parsed_0001558370-23-003469.txt", "example.mda_0001558370-23-003469.txt", True)
