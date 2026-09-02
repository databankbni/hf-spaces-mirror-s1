"""
Heaven on Earth CMS Backend - Supabase Storage Utility

Handles file uploads and management with Supabase Storage.
"""
import os
import uuid
from typing import Optional, Tuple
from fastapi import UploadFile, HTTPException, status
from supabase import create_client, Client as SupabaseClient
from app.config import settings

class SupabaseStorage:
    _instance: Optional['SupabaseStorage'] = None
    _client: Optional[SupabaseClient] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SupabaseStorage, cls).__new__(cls)
            cls._client = create_client(
                settings.supabase_url,
                settings.supabase_key
            )
        return cls._instance
    
    @property
    def client(self) -> SupabaseClient:
        if not self._client:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Supabase client not initialized"
            )
        return self._client
    
    async def upload_file(
        self,
        file: UploadFile,
        bucket: str = "folders",
        path: str = ""
    ) -> Tuple[str, str]:
        """
        Upload a file to Supabase Storage.
        
        Args:
            file: The file to upload
            bucket: The storage bucket name (default: "gallery")
            path: Optional path within the bucket (e.g., "images/2023/")
            
        Returns:
            Tuple of (public_url, file_path)
        """
        try:
            # Generate a unique filename
            file_extension = os.path.splitext(file.filename)[1].lower()
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = os.path.join(path, unique_filename).lstrip("/")
            
            # Read file content
            content = await file.read()
            
            # Upload to Supabase
            result = self.client.storage.from_(bucket).upload(
                file_path,
                content,
                {"content-type": file.content_type or "application/octet-stream"}
            )
            
            # Get public URL
            response = self.client.storage.from_(bucket).get_public_url(file_path)
            
            return response, file_path
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error uploading file: {str(e)}"
            )
    
    def delete_file(self, file_path: str, bucket: str = "folders") -> bool:
        """
        Delete a file from Supabase Storage.
        
        Args:
            file_path: Path to the file in the bucket
            bucket: The storage bucket name (default: "gallery")
            
        Returns:
            bool: True if deletion was successful
        """
        try:
            self.client.storage.from_(bucket).remove([file_path])
            return True
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting file: {str(e)}"
            )

# Create a singleton instance
supabase_storage = SupabaseStorage()
