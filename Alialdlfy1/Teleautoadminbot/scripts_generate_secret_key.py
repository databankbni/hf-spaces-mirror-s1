try:
    from cryptography.fernet import Fernet
except ImportError:
    raise SystemExit('Install cryptography first: pip install cryptography')
print(Fernet.generate_key().decode())
