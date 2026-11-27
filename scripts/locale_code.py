"""Generate translated text without one compiler graph spanning every language."""
import json

# Keep escaped native literals below the compiler's 4 KiB statement limit.
LOCALE_PIECE = 800


def translation_code(values_by_language):
    languages = list(values_by_language)
    english = languages.index('en') if 'en' in languages else None
    fallback = f'GameLocaleTextLanguage{english}(key)' if english is not None else '""'
    code = '#import "std/vec"\nGameLocaleText :: (language: string, key: string) -> string {\n'
    for index, language in enumerate(languages):
        if language != 'en':
            code += f'    if language == {json.dumps(language)} {{ return GameLocaleTextLanguage{index}(key) }}\n'
    code += f'    return {fallback}\n}}\n'
    # Each language is a separate procedure. Keeping their control-flow graphs
    # separate avoids quadratic memory growth in browser Wasm compilation.
    longs = []
    for index, language in enumerate(languages):
        code += f'GameLocaleTextLanguage{index} :: (key: string) -> string {{\n'
        for key, value in values_by_language[language].items():
            if len(value.encode()) <= LOCALE_PIECE:
                text = json.dumps(value, ensure_ascii=False)
            else:
                text = f'GameLocaleTextLong{len(longs)}()'
                longs.append(value)
            code += '    if key == ' + json.dumps(key) + ' { return ' + text + ' }\n'
        code += '    return ' + ('""' if language == 'en' else fallback) + '\n}\n'
    for index, value in enumerate(longs):
        data = value.encode()
        pieces, start = [], 0
        while start < len(data):
            end = min(start + LOCALE_PIECE, len(data))
            while end < len(data) and data[end] & 0xc0 == 0x80:
                end -= 1
            pieces.append(data[start:end].decode())
            start = end
        name = f'GameLocaleTextLong{index}'
        code += f'{name}Text: string;\n'
        code += f'{name} :: () -> string {{\n    if {name}Text.count == 0 {{\n        built: Vec(u8)\n'
        for piece in pieces:
            code += f'        BuilderPrint(*built, "%", {json.dumps(piece, ensure_ascii=False)})\n'
        code += f'        {name}Text = BuilderFinish(built)\n    }}\n    return {name}Text\n}}\n'
    return code
