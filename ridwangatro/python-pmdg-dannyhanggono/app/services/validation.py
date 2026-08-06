"""
Data Validation Service
Backend validation for patient data with comprehensive rules.
"""

from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field, validator
import re


class ValidationError(BaseModel):
    """Validation error detail"""
    field: str
    message: str
    value: Optional[Any] = None


class ValidationResult(BaseModel):
    """Result of validation"""
    valid: bool
    errors: List[ValidationError] = []
    sanitized_data: Optional[Dict[str, Any]] = None


class PatientValidationRules:
    """Validation rules for patient data"""
    
    # No.RM format: XX.XX.XX
    RM_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")
    
    # Date format: YYYY-MM-DD
    DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    
    # Allowed values
    ALLOWED_GENDER = ["Laki-laki", "Perempuan", "L", "P"]
    ALLOWED_PAYMENT = ["BPJS", "UMUM"]
    ALLOWED_ACTIONS = [
        "Obat", "Cabut Anak", "Cabut Dewasa", 
        "Tambal Sementara", "Tambal Tetap", "Scaling", "Rujuk"
    ]


class ValidationService:
    """Service for validating and sanitizing patient data"""
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self.rules = PatientValidationRules()
    
    def validate_patient(self, data: Dict[str, Any]) -> ValidationResult:
        """
        Validate patient data.
        Returns ValidationResult with errors if invalid.
        """
        errors: List[ValidationError] = []
        sanitized: Dict[str, Any] = {}
        
        # 1. Validate and sanitize Nama Pasien
        nama = data.get("Nama Pasien", "").strip()
        if not nama:
            errors.append(ValidationError(
                field="Nama Pasien",
                message="Nama pasien wajib diisi"
            ))
        elif len(nama) < 3:
            errors.append(ValidationError(
                field="Nama Pasien",
                message="Nama pasien minimal 3 karakter",
                value=nama
            ))
        elif len(nama) > 100:
            errors.append(ValidationError(
                field="Nama Pasien",
                message="Nama pasien maksimal 100 karakter",
                value=nama
            ))
        else:
            sanitized["Nama Pasien"] = nama.upper()  # Standardize to uppercase
        
        # 2. Validate No.RM format
        no_rm = data.get("No.RM", "").strip()
        if not no_rm:
            errors.append(ValidationError(
                field="No.RM",
                message="No. RM wajib diisi"
            ))
        elif not self.rules.RM_PATTERN.match(no_rm):
            errors.append(ValidationError(
                field="No.RM",
                message="Format No. RM harus XX.XX.XX (contoh: 01.23.45)",
                value=no_rm
            ))
        else:
            sanitized["No.RM"] = no_rm
        
        # 3. Validate Tanggal Kunjungan
        tanggal = data.get("Tanggal Kunjungan", "").strip()
        if not tanggal:
            errors.append(ValidationError(
                field="Tanggal Kunjungan",
                message="Tanggal kunjungan wajib diisi"
            ))
        elif not self.rules.DATE_PATTERN.match(tanggal):
            errors.append(ValidationError(
                field="Tanggal Kunjungan",
                message="Format tanggal harus YYYY-MM-DD",
                value=tanggal
            ))
        else:
            sanitized["Tanggal Kunjungan"] = tanggal
        
        # 4. Validate Kelamin
        kelamin = data.get("Kelamin", "").strip()
        if not kelamin:
            errors.append(ValidationError(
                field="Kelamin",
                message="Kelamin wajib dipilih"
            ))
        elif kelamin not in self.rules.ALLOWED_GENDER:
            errors.append(ValidationError(
                field="Kelamin",
                message=f"Kelamin harus salah satu dari: {', '.join(self.rules.ALLOWED_GENDER)}",
                value=kelamin
            ))
        else:
            # Normalize gender
            if kelamin == "L":
                kelamin = "Laki-laki"
            elif kelamin == "P":
                kelamin = "Perempuan"
            sanitized["Kelamin"] = kelamin
        
        # 5. Validate Biaya (payment type)
        biaya = data.get("Biaya", "").strip()
        if not biaya:
            errors.append(ValidationError(
                field="Biaya",
                message="Jenis pasien wajib dipilih"
            ))
        elif biaya not in self.rules.ALLOWED_PAYMENT:
            errors.append(ValidationError(
                field="Biaya",
                message=f"Jenis pasien harus: {' atau '.join(self.rules.ALLOWED_PAYMENT)}",
                value=biaya
            ))
        else:
            sanitized["Biaya"] = biaya
        
        # 6. Copy valid action fields
        for action in self.rules.ALLOWED_ACTIONS:
            if data.get(action) == "Ya":
                sanitized[action] = "Ya"
        
        # 7. Sanitize Lainnya (optional field)
        lainnya = data.get("Lainnya", "")
        if lainnya:
            # Remove potentially dangerous characters
            sanitized["Lainnya"] = re.sub(r"[<>\"']", "", lainnya.strip())[:200]
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            sanitized_data=sanitized if len(errors) == 0 else None
        )
    
    async def check_rm_unique(self, no_rm: str, exclude_id: Optional[str] = None) -> bool:
        """Check if No.RM is unique in database"""
        if not self.db_pool:
            return True  # Skip check if no DB connection
        
        try:
            async with self.db_pool.acquire() as conn:
                query = "SELECT COUNT(*) FROM data_entries WHERE medical_record_number = $1"
                args = [no_rm]
                
                if exclude_id:
                    query += " AND id != $2"
                    args.append(exclude_id)
                
                count = await conn.fetchval(query, *args)
                return count == 0
        except Exception:
            return True  # Default to allowing if DB check fails


# Singleton instance
validation_service = ValidationService()
