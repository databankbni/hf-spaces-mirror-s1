"""Standalone Lilylet tokenizer (vendored from deep-starry, torch-free).

Trimmed to what inference needs: load the vocab artifact, expose the special
ids + the id->text table, and encode text to ids (longest protected-token match
first, then per-character, then byte-level fallback). The training-time unknown
tracking and the patchify/packing machinery are intentionally dropped.

Source: deep-starry/starry/lilylet/data/patchifier.py (LilyletTokenizer).
"""

import json
from typing import List


class LilyletTokenizer:
	def __init__ (self, tokenizer_path: str):
		self.path = tokenizer_path
		with open(tokenizer_path, 'r', encoding='utf-8') as f:
			self.artifact = json.load(f)

		self.vocab = self.artifact['vocab']
		self.id_by_token = {entry['token']: entry['id'] for entry in self.vocab}
		self.text_by_id = {entry['id']: entry.get('text', entry['token']) for entry in self.vocab}
		self.unknown_id = self.id_by_token.get('<unknown>', 3)
		self.pad_id = self.id_by_token.get('<pad>', 0)
		self.bos_id = self.id_by_token.get('<bos>', 1)
		self.eos_id = self.id_by_token.get('<eos>', 2)
		self.vocab_size = max(entry['id'] for entry in self.vocab) + 1

		fixed = [entry['token'] for entry in self.vocab if entry.get('type') == 'protected']
		self.fixed_tokens = sorted(set(fixed), key=lambda token: (-len(token), token))

	def encode (self, text: str) -> List[int]:
		ids: List[int] = []
		i = 0
		while i < len(text):
			matched = None
			for token in self.fixed_tokens:
				if text.startswith(token, i):
					matched = token
					break
			if matched is not None:
				ids.append(self.id_by_token[matched])
				i += len(matched)
				continue

			char = text[i]
			if char in self.id_by_token:
				ids.append(self.id_by_token[char])
			else:
				emitted_unknown = False
				for byte in char.encode('utf-8'):
					if 0x08 <= byte <= 0x7f and byte in self.text_by_id:
						ids.append(byte)
					else:
						emitted_unknown = True
				if emitted_unknown:
					ids.append(self.unknown_id)
			i += 1
		return ids
