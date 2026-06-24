import os
from datetime import datetime

# ── Что пропускаем ────────────────────────────────────────────────────────────

SKIP_DIRS = {
    '__pycache__', '.git', '.svn', '.hg', '.idea', '.vscode',
    'node_modules', '.next', '.nuxt', 'dist', 'build', '.cache',
    'venv', '.venv', 'env', '.env', '.mypy_cache', '.pytest_cache',
    '.tox', 'coverage', '.coverage', '__snapshots__',
}

SKIP_FILES = {
    '.gitignore', '.gitattributes', '.gitmodules',
    '.dockerignore', '.npmignore', '.eslintignore',
    '.DS_Store', 'Thumbs.db', 'desktop.ini',
    'package-lock.json', 'yarn.lock', 'poetry.lock', 'Pipfile.lock',
}

SKIP_EXTENSIONS = {
    # Бинарники / медиа
    '.exe', '.dll', '.so', '.dylib', '.pyd', '.pyc', '.pyo',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.bz2',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.svg', '.webp',
    '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.db', '.sqlite', '.sqlite3',
    '.bin', '.dat', '.pkl', '.npy', '.npz',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.map',  # source maps
}

# Расширения, из которых читаем код/текст
CODE_EXTENSIONS = {
    # Python
    '.py', '.pyi',
    # Web
    '.js', '.jsx', '.ts', '.tsx', '.html', '.htm', '.css', '.scss', '.sass', '.less', '.vue',
    # Backend / системное
    '.go', '.rs', '.c', '.cpp', '.cc', '.h', '.hpp', '.cs', '.java', '.kt', '.swift',
    '.rb', '.php', '.lua', '.r', '.m', '.scala', '.ex', '.exs', '.erl',
    # Shell
    '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
    # Конфиги (текстовые)
    '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.env',
    '.xml', '.plist',
    # Docs / разметка
    '.md', '.rst', '.txt',
    # Прочее
    '.sql', '.graphql', '.proto', '.tf', '.dockerfile',
    'Dockerfile', 'Makefile', 'Procfile',
}

MAX_FILE_SIZE = 500 * 1024  # 500 КБ — файлы крупнее пропускаем


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_size(size):
    for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} ТБ"


def should_read_code(filename):
    _, ext = os.path.splitext(filename)
    return ext.lower() in CODE_EXTENSIONS or filename in CODE_EXTENSIONS


def should_skip_file(filename):
    _, ext = os.path.splitext(filename)
    return filename in SKIP_FILES or ext.lower() in SKIP_EXTENSIONS


# ── Основная логика ───────────────────────────────────────────────────────────

def collect(root_dir, output_file):
    script_name = os.path.basename(__file__)
    output_name = os.path.basename(output_file)

    lines = []
    lines.append(f"Корневая папка: {root_dir}")
    lines.append(f"Дата сбора: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)

    total_files = 0
    total_dirs = 0
    code_blocks = []  # [(rel_path, content), ...]

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Фильтруем папки прямо в списке, чтобы os.walk не заходил в них
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith('.')
        )

        rel_dir = os.path.relpath(dirpath, root_dir)
        depth = 0 if rel_dir == '.' else rel_dir.count(os.sep) + 1
        indent = "  " * depth
        folder_name = os.path.basename(dirpath) if depth > 0 else dirpath
        lines.append(f"\n{indent}[{folder_name}]")
        total_dirs += 1

        file_indent = "  " * (depth + 1)
        for filename in sorted(filenames):
            if filename in (script_name, output_name):
                continue
            if should_skip_file(filename):
                continue

            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, root_dir)

            try:
                size = os.path.getsize(filepath)
                size_str = format_size(size)
            except OSError:
                size_str = "???"
                size = 0

            lines.append(f"{file_indent}{filename}  ({size_str})")
            total_files += 1

            # Читаем код если файл подходит и не слишком большой
            if should_read_code(filename) and size <= MAX_FILE_SIZE:
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    code_blocks.append((rel_path, content))
                except OSError:
                    pass

    # Итог по структуре
    lines.append(f"\n{'=' * 70}")
    lines.append(f"Итого папок: {total_dirs}, файлов: {total_files}")

    # Блок с кодом
    lines.append(f"\n\n{'=' * 70}")
    lines.append("СОДЕРЖИМОЕ ФАЙЛОВ")
    lines.append(f"{'=' * 70}")

    for rel_path, content in code_blocks:
        lines.append(f"\n\n{'─' * 70}")
        lines.append(f"Файл: {rel_path}")
        lines.append(f"{'─' * 70}")
        lines.append(content)

    # Пишем файл (перезаписываем если уже есть)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"Готово! Папок: {total_dirs}, файлов: {total_files}, с кодом: {len(code_blocks)}")
    print(f"Результат: {output_file}")


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, "filesystem.txt")
    collect(script_dir, output_path)