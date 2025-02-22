
import os
import re
from colorthief import ColorThief
import imagesize
from hashlib import sha256

from FileFinder import FileFinder
from MongoDatabase import MongoDatabase


class AssetProcessor:
	def __init__(self, file_finder: FileFinder, database: MongoDatabase):
		self.file_finder = file_finder
		self.collection_assets = database.get_collection("assets")
		self.local_assets = file_finder.find_local_assets()
		self.fast_mode = False

	def set_fast_mode(self, fast_mode: bool):
		self.fast_mode = fast_mode

	def is_remote(self, path: str) -> bool:
		"""
		returns True if path is a remote url
		"""
		if re.match(r'^https?://', path):
			return True

		return False

	def get_extension(self, path: str) -> str:
		"""
		returns file extension of path
		"""
		# strip query string
		path = path.split('?')[0]

		return os.path.splitext(path)[-1].replace('.', '').lower()

	def get_file_type(self, path: str, extension) -> str:
		if extension is None:
			return None
		elif extension in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
			return 'image'
		elif extension in ('mp4', 'webm', 'mov'):
			return 'video'
		elif extension in('mp3', 'ogg', 'wav'):
			return 'audio'
		else:
			return 'unknown'


	def get_image_size(self, path: str, local_path_exists: bool, filetype: str) -> tuple:
		"""
		returns image size as tuple (width, height)
		"""
		# we don't know the size of remote images without downloading them
		if not local_path_exists:
			return None, None

		# file has no known image extension
		if filetype != 'image':
			return None, None

		try:
			return imagesize.get(path)
		except:
			print("Error: Could not get image size of " + path)
			return None, None

	def get_file_size(self, local_path_exists: bool, path: str) -> int:
		"""
		returns file size in bytes
		"""
		if not local_path_exists:
			return None

		return os.path.getsize(path)

	def get_filename_with_hash(self, path: str, is_remote: bool) -> str:
		# local path
		if not is_remote:
			return os.path.basename(path)

		# remote path (url)
		filename = re.match(r'.+/([^?]*)', path).groups()[0]
		filename_without_ext, filename_ext = os.path.splitext(filename)

		if len(filename_ext) > 41:
			filename_without_ext = filename
			filename_ext = ""

		# hashed filename must contain get parameters
		hash_sha256 = sha256(path.encode('utf-8')).hexdigest()[:5].upper()

		# remove get parameters
		# filename = filename.split('?')[0]
		# base, extension = os.path.splitext(filename)
		filename = filename_without_ext[:42] + "-" + hash_sha256 + filename_ext
		return filename

	def strip_hash_from_filename(self, filename: str) -> str:
		"""
		removes hash from filename
		"""
		return re.sub(r'-[A-F0-9]{5}(?=\..+)?$', '', filename)

	def get_colors(self, path: str, local_path_exists: bool, filetype: str):
		"""
		returns dominant color and palette of image
		this is very slow, so do it only if fast mode is disabled
		"""
		if self.fast_mode:
			return None, None

		if not local_path_exists:
			return None, None

		if filetype != 'image':
			return None, None

		try:
			color_thief = ColorThief(path)
			dominant_color = color_thief.get_color(quality=1)
			palette = color_thief.get_palette(color_count=6)
			return dominant_color, palette
		except:
			print("Error: Could not get colors of " + path)
			return None, None

	def get_cached_asset(self, filename_with_hash: str) -> bool:
		"""
		returns asset content if asset has already been processed (fetch from database)
		if asset not found in database returns None
		"""
		cached_asset = self.collection_assets.find_one({"_id": filename_with_hash})
		if cached_asset is None:
			return None

		return cached_asset

	def insert_asset(self, asset: dict):
		"""
		inserts asset into database
		"""
		self.collection_assets.insert_one(asset)

	def get_local_path(self, filename_with_hash: str) -> str:
		"""
		returns local path of asset
		"""
		if filename_with_hash in self.local_assets:
			return self.local_assets[filename_with_hash]
		else:
			print("Error: Could not find local path of " + filename_with_hash)
			return None

	def process(self, original_filepath: str):
		"""
		provide filepath without base directory
		original_filepath is the path from json file, but is not necessarily a valid path
		"""
		if original_filepath == None:
			return
		original_filepath = self.file_finder.normalize_path(original_filepath)

		is_remote = self.is_remote(original_filepath)
		filename_with_hash = self.get_filename_with_hash(original_filepath, is_remote)

		cached_asset = self.get_cached_asset(filename_with_hash)
		if cached_asset is not None:
			return cached_asset

		remote_url = original_filepath if is_remote else None
		local_path = self.get_local_path(filename_with_hash)
		local_path_exists = True if local_path is not None else False

		extension = self.get_extension(original_filepath)
		filetype = self.get_file_type(original_filepath, extension)
		width, height = self.get_image_size(local_path, local_path_exists, filetype)
		size_bytes = self.get_file_size(local_path_exists, local_path)
		filename_without_hash = self.strip_hash_from_filename(filename_with_hash)
		dominant_color, palette = self.get_colors(local_path, local_path_exists, filetype)

		local_path_without_base = self.file_finder.remove_base_directory(local_path)
		if local_path_without_base is not None:
			path = local_path_without_base
		elif remote_url is not None:
			path = remote_url
		else:
			path = None

		asset = {
			"_id": filename_with_hash,
			"originalPath": original_filepath,
			"localPath": local_path_without_base,
			"remotePath": remote_url,
			"path": path,
			"extension": extension,
			"type": filetype,
			"width": width,
			"height": height,
			"sizeBytes": size_bytes,
			"filenameWithHash": filename_with_hash,
			"filenameWithoutHash": filename_without_hash,
			"colorDominant": dominant_color,
			"colorPalette": palette,
		}

		self.insert_asset(asset)
		return asset