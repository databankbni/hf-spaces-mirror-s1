"""
PDF Generator Service
Generates various PDF documents for dental clinic
"""

from io import BytesIO
from typing import List, Optional, Dict, Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, 
    Image, HRFlowable
)
from datetime import datetime


class PDFGenerator:
    """Generate PDF documents for dental clinic"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        self.styles.add(ParagraphStyle(
            name='TitleCenter',
            parent=self.styles['Heading1'],
            fontSize=18,
            spaceAfter=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#1a365d')
        ))
        
        self.styles.add(ParagraphStyle(
            name='SubtitleCenter',
            parent=self.styles['Heading2'],
            fontSize=12,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#4a5568')
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading3'],
            fontSize=11,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor('#2d3748')
        ))
        
        body_style = self.styles['BodyText']
        body_style.fontSize = 10
        body_style.spaceAfter = 4
        body_style.leading = 14
        
        self.styles.add(ParagraphStyle(
            name='Footer',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#718096'),
            alignment=TA_CENTER
        ))
    
    def _create_header(self) -> List:
        """Create standard header for all PDFs"""
        elements = []
        
        # Clinic name
        elements.append(Paragraph(
            "PRAKTEK MANDIRI DOKTER GIGI",
            self.styles['TitleCenter']
        ))
        elements.append(Paragraph(
            "drg. Danny Hanggono",
            self.styles['SubtitleCenter']
        ))
        
        # Separator line
        elements.append(HRFlowable(
            width="100%",
            thickness=1,
            color=colors.HexColor('#e2e8f0'),
            spaceBefore=5,
            spaceAfter=15
        ))
        
        return elements
    
    def _create_footer(self) -> List:
        """Create footer with timestamp"""
        elements = []
        elements.append(Spacer(1, 30))
        elements.append(HRFlowable(
            width="100%",
            thickness=0.5,
            color=colors.HexColor('#e2e8f0'),
            spaceBefore=10,
            spaceAfter=5
        ))
        elements.append(Paragraph(
            f"Dicetak pada: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Dokumen ini dihasilkan secara otomatis",
            self.styles['Footer']
        ))
        return elements
    
    def generate_medical_record(self, data: Dict[str, Any]) -> bytes:
        """
        Generate medical record PDF
        
        Args:
            data: Dictionary containing:
                - patient_name: str
                - medical_record_number: str
                - visit_date: str
                - gender: str ('L' or 'P')
                - payment_type: str
                - actions: List[str]
                - other_actions: Optional[str]
        
        Returns:
            PDF as bytes
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )
        
        elements = []
        
        # Header
        elements.extend(self._create_header())
        
        # Document title
        elements.append(Paragraph(
            "REKAM MEDIS PASIEN",
            ParagraphStyle(
                'DocTitle',
                parent=self.styles['Heading2'],
                alignment=TA_CENTER,
                spaceAfter=20,
                textColor=colors.HexColor('#2b6cb0')
            )
        ))
        
        # Patient info table
        gender_text = "Laki-laki" if data.get("gender") == "L" else "Perempuan"
        patient_data = [
            ["Nama Pasien", ":", data.get("patient_name", "-")],
            ["No. Rekam Medis", ":", data.get("medical_record_number", "-")],
            ["Jenis Kelamin", ":", gender_text],
            ["Tanggal Kunjungan", ":", data.get("visit_date", "-")],
            ["Jenis Pembayaran", ":", data.get("payment_type", "-")],
        ]
        
        patient_table = Table(patient_data, colWidths=[5*cm, 0.5*cm, 10*cm])
        patient_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f7fafc')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2d3748')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('ALIGN', (2, 0), (2, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        elements.append(patient_table)
        elements.append(Spacer(1, 20))
        
        # Actions section
        elements.append(Paragraph("Tindakan yang Dilakukan:", self.styles['SectionHeader']))
        
        actions = data.get("actions", [])
        if actions:
            for i, action in enumerate(actions, 1):
                elements.append(Paragraph(
                    f"&nbsp;&nbsp;&nbsp;{i}. {action}",
                    self.styles['BodyText']
                ))
        else:
            elements.append(Paragraph(
                "&nbsp;&nbsp;&nbsp;- Tidak ada tindakan tercatat",
                self.styles['BodyText']
            ))
        
        # Other actions
        if data.get("other_actions"):
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Keterangan Tambahan:", self.styles['SectionHeader']))
            elements.append(Paragraph(
                f"&nbsp;&nbsp;&nbsp;{data['other_actions']}",
                self.styles['BodyText']
            ))
        
        # Signature area
        elements.append(Spacer(1, 40))
        
        sig_data = [
            ["", f"Jakarta, {datetime.now().strftime('%d %B %Y')}"],
            ["", ""],
            ["", ""],
            ["", ""],
            ["", "_" * 30],
            ["", "Dokter Gigi"]
        ]
        sig_table = Table(sig_data, colWidths=[10*cm, 6*cm])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
        ]))
        elements.append(sig_table)
        
        # Footer
        elements.extend(self._create_footer())
        
        doc.build(elements)
        return buffer.getvalue()
    
    def generate_receipt(self, data: Dict[str, Any]) -> bytes:
        """
        Generate receipt/kwitansi PDF
        
        Args:
            data: Dictionary containing:
                - patient_name: str
                - medical_record_number: str
                - date: str
                - actions: List[str]
                - total_amount: int
                - payment_method: str
        
        Returns:
            PDF as bytes
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )
        
        elements = []
        
        # Header
        elements.extend(self._create_header())
        
        # Document title
        elements.append(Paragraph(
            "KWITANSI PEMBAYARAN",
            ParagraphStyle(
                'DocTitle',
                parent=self.styles['Heading2'],
                alignment=TA_CENTER,
                spaceAfter=20,
                textColor=colors.HexColor('#38a169')
            )
        ))
        
        # Receipt info
        elements.append(Paragraph(
            f"No. Kwitansi: KWT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            ParagraphStyle('ReceiptNo', parent=self.styles['Normal'], alignment=TA_RIGHT)
        ))
        elements.append(Spacer(1, 15))
        
        # Patient info
        info_data = [
            ["Diterima dari", ":", data.get("patient_name", "-")],
            ["No. RM", ":", data.get("medical_record_number", "-")],
            ["Tanggal", ":", data.get("date", "-")],
        ]
        info_table = Table(info_data, colWidths=[4*cm, 0.5*cm, 11*cm])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 20))
        
        # Services table
        elements.append(Paragraph("Untuk Pembayaran:", self.styles['SectionHeader']))
        
        service_data = [["No.", "Tindakan"]]
        actions = data.get("actions", [])
        for i, action in enumerate(actions, 1):
            service_data.append([str(i), action])
        
        service_table = Table(service_data, colWidths=[1.5*cm, 14*cm])
        service_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#48bb78')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(service_table)
        elements.append(Spacer(1, 20))
        
        # Total
        total_amount = data.get("total_amount", 0)
        total_formatted = f"Rp {total_amount:,.0f}".replace(",", ".")
        
        total_data = [
            ["Total Pembayaran", total_formatted],
            ["Metode Pembayaran", data.get("payment_method", "-")]
        ]
        total_table = Table(total_data, colWidths=[12*cm, 4*cm])
        total_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f0fff4')),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#48bb78')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(total_table)
        
        # Signature
        elements.append(Spacer(1, 40))
        elements.append(Paragraph(
            f"Jakarta, {datetime.now().strftime('%d %B %Y')}",
            ParagraphStyle('Date', parent=self.styles['Normal'], alignment=TA_RIGHT)
        ))
        elements.append(Spacer(1, 30))
        elements.append(Paragraph(
            "_" * 25 + "<br/>Penerima",
            ParagraphStyle('Sig', parent=self.styles['Normal'], alignment=TA_RIGHT)
        ))
        
        # Footer
        elements.extend(self._create_footer())
        
        doc.build(elements)
        return buffer.getvalue()
    
    def generate_prescription(self, data: Dict[str, Any]) -> bytes:
        """
        Generate prescription/resep PDF
        
        Args:
            data: Dictionary containing:
                - patient_name: str
                - date: str
                - medications: List[dict] with 'name', 'dosage', 'instructions'
                - notes: Optional[str]
        
        Returns:
            PDF as bytes
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )
        
        elements = []
        
        # Header
        elements.extend(self._create_header())
        
        # Rx symbol
        elements.append(Paragraph(
            "℞",
            ParagraphStyle(
                'Rx',
                parent=self.styles['TitleCenter'],
                fontSize=36,
                textColor=colors.HexColor('#3182ce')
            )
        ))
        
        # Patient info
        elements.append(Paragraph(
            f"<b>Pro:</b> {data.get('patient_name', '-')}",
            self.styles['BodyText']
        ))
        elements.append(Paragraph(
            f"<b>Tanggal:</b> {data.get('date', '-')}",
            self.styles['BodyText']
        ))
        elements.append(Spacer(1, 20))
        
        # Medications
        medications = data.get("medications", [])
        if medications:
            med_data = [["No.", "Nama Obat", "Dosis", "Aturan Pakai"]]
            for i, med in enumerate(medications, 1):
                med_data.append([
                    str(i),
                    med.get("name", "-"),
                    med.get("dosage", "-"),
                    med.get("instructions", "-")
                ])
            
            med_table = Table(med_data, colWidths=[1*cm, 5*cm, 3*cm, 6*cm])
            med_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3182ce')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
            ]))
            elements.append(med_table)
        else:
            elements.append(Paragraph("Tidak ada obat yang diresepkan", self.styles['BodyText']))
        
        # Notes
        if data.get("notes"):
            elements.append(Spacer(1, 20))
            elements.append(Paragraph("Catatan:", self.styles['SectionHeader']))
            elements.append(Paragraph(data["notes"], self.styles['BodyText']))
        
        # Signature
        elements.append(Spacer(1, 50))
        elements.append(Paragraph(
            "drg. Danny Hanggono<br/>SIP: 33.17.59219/DG/03.449.1/14/VI/2022",
            ParagraphStyle('DocSig', parent=self.styles['Normal'], alignment=TA_RIGHT)
        ))
        
        # Footer
        elements.extend(self._create_footer())
        
        doc.build(elements)
        return buffer.getvalue()

    def generate_monthly_report(self, data: Dict[str, Any]) -> bytes:
        """
        Generate monthly report PDF with professional formatting.

        Args:
            data: Dictionary containing:
                - year: int
                - month: int
                - count: int
                - patients: List[Dict] with patient visit data
                - summary: Dict with totalBPJS, totalUmum, totalLaki, totalPerempuan, tindakan
                - clinic_name: str (optional)
                - doctor_name: str (optional)

        Returns:
            PDF as bytes
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=1.5*cm,
            leftMargin=1.5*cm,
            topMargin=1.5*cm,
            bottomMargin=1.5*cm
        )

        elements = []
        month_names = [
            'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
            'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
        ]
        month_name = month_names[data.get('month', 1) - 1]
        year = data.get('year', datetime.now().year)
        period = f"{month_name} {year}"

        clinic = data.get('clinic_name', 'PRAKTEK MANDIRI DOKTER GIGI')
        doctor = data.get('doctor_name', 'drg. Danny Hanggono')
        summary = data.get('summary', {})
        patients = data.get('patients', [])
        count = data.get('count', 0)
        tindakan = summary.get('tindakan', {})

        # ===== HEADER BLOCK =====
        elements.append(Paragraph(
            clinic,
            ParagraphStyle('ClinicName', parent=self.styles['TitleCenter'],
                           fontSize=16, textColor=colors.HexColor('#0f766e'))
        ))
        elements.append(Paragraph(
            doctor,
            ParagraphStyle('DoctorName', parent=self.styles['Normal'],
                           fontSize=11, alignment=TA_CENTER,
                           textColor=colors.HexColor('#115e59'))
        ))
        elements.append(Spacer(1, 2))
        elements.append(Paragraph(
            'Rembang, Jawa Tengah',
            ParagraphStyle('Address', parent=self.styles['Normal'],
                           fontSize=8, alignment=TA_CENTER,
                           textColor=colors.HexColor('#64748b'))
        ))
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width="100%", thickness=2,
                                    color=colors.HexColor('#0f766e'),
                                    spaceBefore=2, spaceAfter=2))
        elements.append(Paragraph(
            f"LAPORAN BULANAN — {period.upper()}",
            ParagraphStyle('ReportTitle', parent=self.styles['Heading2'],
                           alignment=TA_CENTER, spaceAfter=12,
                           textColor=colors.HexColor('#115e59'))
        ))
        elements.append(HRFlowable(width="100%", thickness=0.5,
                                    color=colors.HexColor('#cbd5e1'),
                                    spaceBefore=2, spaceAfter=12))

        # ===== SUMMARY SECTION =====
        elements.append(Paragraph(
            'RINGKASAN STATISTIK',
            ParagraphStyle('SecTitle', parent=self.styles['Heading3'],
                           fontSize=11, textColor=colors.HexColor('#115e59'))
        ))

        unique_dates = len(set(
            p.get('tanggal') or p.get('visitDate') or ''
            for p in patients if p.get('tanggal') or p.get('visitDate')
        ))
        daily_avg = round(count / unique_dates) if unique_dates > 0 else 0

        stat_data = [[
            Paragraph(f"<b>{count}</b><br/><font size='7'>Total Pasien</font>",
                      self.styles['BodyText']),
            Paragraph(f"<b>{summary.get('totalLaki', 0)}</b><br/><font size='7'>Laki-laki</font>",
                      self.styles['BodyText']),
            Paragraph(f"<b>{summary.get('totalPerempuan', 0)}</b><br/><font size='7'>Perempuan</font>",
                      self.styles['BodyText']),
            Paragraph(f"<b>{daily_avg}</b><br/><font size='7'>Rata-rata/Hari</font>",
                      self.styles['BodyText']),
        ]]
        stat_table = Table(stat_data, colWidths=[4.5*cm]*4)
        stat_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTSIZE', (0, 0), (-1, -1), 14),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]),
        ]))
        elements.append(stat_table)
        elements.append(Spacer(1, 6))

        # BPJS/UMUM bar
        total_bpjs = summary.get('totalBPJS', 0)
        total_umum = summary.get('totalUmum', 0)
        if count > 0:
            bpjs_pct = total_bpjs / count
            umum_pct = total_umum / count
            bar_data = [[
                Paragraph(f"BPJS: {total_bpjs} ({round(bpjs_pct*100)}%)",
                          ParagraphStyle('bpjs', parent=self.styles['BodyText'],
                                         fontSize=8, textColor=colors.white)),
                Paragraph(f"UMUM: {total_umum} ({round(umum_pct*100)}%)",
                          ParagraphStyle('umum', parent=self.styles['BodyText'],
                                         fontSize=8, textColor=colors.white,
                                         alignment=TA_RIGHT)),
            ]]
            bar_table = Table(bar_data, colWidths=[
                max(2*cm, 10*cm * bpjs_pct),
                max(2*cm, 10*cm * umum_pct)
            ])
            bar_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#047857')),
                ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#2563eb')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ]))
            elements.append(bar_table)
        elements.append(Spacer(1, 10))

        # ===== TINDAKAN BREAKDOWN =====
        tindakan_order = ['Obat', 'Cabut Anak', 'Cabut Dewasa',
                          'Tambal Sementara', 'Tambal Tetap', 'Scaling', 'Rujuk', 'Lainnya']
        tdata = []
        for i, name in enumerate(tindakan_order, 1):
            val = tindakan.get(name, 0)
            if val > 0:
                pct = round(val / count * 100) if count > 0 else 0
                tdata.append([str(i), name, str(val), f"{pct}%"])

        if tdata:
            elements.append(Paragraph(
                'DISTRIBUSI TINDAKAN MEDIS',
                ParagraphStyle('SecTitle2', parent=self.styles['Heading3'],
                               fontSize=11, textColor=colors.HexColor('#115e59'))
            ))
            total_t = sum(tindakan.get(n, 0) for n in tindakan_order)
            tdata.append(['', 'TOTAL TINDAKAN', str(total_t), ''])
            t_table = Table(
                [['No', 'Tindakan Medis', 'Jumlah', '% Pasien']] + tdata,
                colWidths=[1*cm, 6*cm, 2*cm, 2.5*cm]
            )
            t_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (2, 0), (3, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#d6dde6')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -2),
                 [colors.HexColor('#f8fafc'), colors.white]),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e6f5f2')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(t_table)
            elements.append(Spacer(1, 10))

        # ===== DAILY SUMMARY TABLE =====
        daily_map = {}
        for p in patients:
            d = p.get('tanggal') or p.get('visitDate') or ''
            if not d:
                continue
            if d not in daily_map:
                daily_map[d] = {'total': 0, 'bpjs': 0, 'umum': 0,
                                'laki': 0, 'perempuan': 0}
            daily_map[d]['total'] += 1
            jns = (p.get('jenis_pasien') or p.get('paymentType') or '').upper()
            if jns == 'BPJS':
                daily_map[d]['bpjs'] += 1
            else:
                daily_map[d]['umum'] += 1
            kl = (p.get('kelamin') or p.get('gender') or '').lower()
            if kl in ('l', 'laki-laki'):
                daily_map[d]['laki'] += 1
            else:
                daily_map[d]['perempuan'] += 1

        sorted_dates = sorted(daily_map.keys())
        daily_data = []
        for i, d in enumerate(sorted_dates, 1):
            dd = daily_map[d]
            parts = d.split('-')
            date_label = (f"{int(parts[2])} {month_names[int(parts[1]) - 1]} {parts[0]}"
                         if len(parts) == 3 else d)
            daily_data.append([
                str(i), date_label, str(dd['total']),
                str(dd['laki']), str(dd['perempuan']),
                str(dd['bpjs']), str(dd['umum'])
            ])

        if daily_data:
            elements.append(Paragraph(
                'RINGKASAN HARIAN',
                ParagraphStyle('SecTitle3', parent=self.styles['Heading3'],
                               fontSize=11, textColor=colors.HexColor('#115e59'))
            ))
            d_table = Table(
                [['No', 'Tanggal', 'Total', 'L', 'P', 'BPJS', 'UMUM']] + daily_data,
                colWidths=[1*cm, 3*cm, 1.2*cm, 1*cm, 1*cm, 1.2*cm, 1.2*cm]
            )
            d_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#d6dde6')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                 [colors.HexColor('#f8fafc'), colors.white]),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
            elements.append(d_table)
            elements.append(Spacer(1, 10))

        # ===== PATIENT LIST TABLE =====
        elements.append(Paragraph(
            'DAFTAR KUNJUNGAN PASIEN',
            ParagraphStyle('SecTitle4', parent=self.styles['Heading3'],
                           fontSize=11, textColor=colors.HexColor('#115e59'))
        ))
        elements.append(Paragraph(
            f"Total: {count} kunjungan",
            ParagraphStyle('SubTotal', parent=self.styles['Normal'],
                           fontSize=8, textColor=colors.HexColor('#64748b'))
        ))

        patient_rows = []
        for i, p in enumerate(patients, 1):
            kl = (p.get('kelamin') or p.get('gender') or '').lower()
            kl_label = 'L' if kl in ('l', 'laki-laki') else 'P'
            d = p.get('tanggal') or p.get('visitDate') or ''
            parts = d.split('-')
            date_label = (f"{int(parts[2])} {month_names[int(parts[1]) - 1]} {parts[0]}"
                         if len(parts) == 3 else d)
            acts = ', '.join(p.get('actions') or [])
            lainnya = p.get('lainnya') or ''
            if lainnya and lainnya.strip() and lainnya.strip() != '-':
                acts = f"{acts} + {lainnya}" if acts else lainnya
            patient_rows.append([
                str(i), date_label,
                (p.get('nama_pasien') or p.get('name') or '-').upper(),
                p.get('no_rm') or p.get('medicalRecordNumber') or '-',
                kl_label,
                p.get('jenis_pasien') or p.get('paymentType') or '-',
                Paragraph(acts or '-', ParagraphStyle(
                    'ActCell', parent=self.styles['Normal'],
                    fontSize=7, leading=9, wordWrap='CJK'
                ))
            ])

        p_table = Table(
            [['No', 'Tanggal', 'Nama Pasien', 'No. RM', 'K', 'Jenis', 'Tindakan']] + patient_rows,
            colWidths=[0.8*cm, 2.8*cm, 3.5*cm, 1.5*cm, 0.6*cm, 1.2*cm, 3.6*cm]
        )
        p_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#115e59')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('ALIGN', (3, 0), (5, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.2, colors.HexColor('#d6dde6')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.HexColor('#f8fafc'), colors.white]),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('FONTNAME', (2, 1), (2, -1), 'Helvetica-Bold'),
            ('FONTNAME', (3, 1), (3, -1), 'Courier'),
        ]))

        for i in range(1, len(patient_rows) + 1):
            val = (patient_rows[i-1][5] or '').upper()
            if val == 'BPJS':
                p_table.setStyle(TableStyle([
                    ('TEXTCOLOR', (5, i), (5, i), colors.HexColor('#047857')),
                    ('FONTNAME', (5, i), (5, i), 'Helvetica-Bold'),
                ]))
            elif val == 'UMUM':
                p_table.setStyle(TableStyle([
                    ('TEXTCOLOR', (5, i), (5, i), colors.HexColor('#2563eb')),
                    ('FONTNAME', (5, i), (5, i), 'Helvetica-Bold'),
                ]))

        elements.append(p_table)
        elements.append(Spacer(1, 15))

        # ===== SIGNATURE =====
        now = datetime.now()
        sig_style = ParagraphStyle('SigCenter', parent=self.styles['Normal'],
                                   alignment=TA_CENTER, fontSize=9, leading=14)
        sign_data = [
            ['', Paragraph(
                f"Rembang, {now.day} {month_names[now.month - 1]} {now.year}<br/>"
                f"Dokter Penanggung Jawab,",
                sig_style
            )],
            ['', Spacer(1, 40)],
            ['', Paragraph(
                f"{'_' * 25}<br/>"
                f"<b>{doctor}</b><br/>"
                f"<font size='7'>SIP: 33.17.59219/DG/03.449.1/14/VI/2022</font>",
                sig_style
            )],
        ]
        sign_table = Table(sign_data, colWidths=[8*cm, 6*cm])
        sign_table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(sign_table)

        def add_footer(canvas, doc):
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor('#d6dde6'))
            canvas.setLineWidth(0.3)
            canvas.line(1.5*cm, 1*cm, A4[0] - 1.5*cm, 1*cm)
            canvas.setFont('Helvetica', 7)
            canvas.setFillColor(colors.HexColor('#64748b'))
            canvas.drawString(1.5*cm, 0.7*cm,
                              f"Laporan Bulanan {period} — {clinic}")
            canvas.drawRightString(A4[0] - 1.5*cm, 0.7*cm,
                                   f"Halaman {doc.page}")
            canvas.drawCentredString(A4[0] / 2, 0.7*cm,
                                     f"Dicetak: {now.strftime('%d/%m/%Y %H:%M')}")
            canvas.restoreState()

        doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
        return buffer.getvalue()
