
with open('app/main.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('r"https://.*\.vercel\.app|http://localhost:\d+|http://127\.0\.0\.1:\d+"', '".*"')
with open('app/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed CORS wide open!')

