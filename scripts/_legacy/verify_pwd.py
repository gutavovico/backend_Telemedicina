import sys
sys.path.insert(0, '.')
from app.core.security import verify_password

result = verify_password('admin123', '$2b$12$dummy_hash_1')
print('Verify result:', result)