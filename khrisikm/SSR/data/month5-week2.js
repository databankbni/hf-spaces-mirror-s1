const DASHBOARD_DATA = {
  title: "إنتاجية التعليم الإلكتروني",
  subtitle: "مؤشرات وبرامج التعليم الإلكتروني",
  note: "الأسبوع الثاني من شهر 5",
  lastUpdate: "الأسبوع الثاني",
  footerText: "© التعليم الإلكتروني",

  topStats: [
    { label: "إجمالي الحلق", value: 72 },
    { label: "إجمالي المعلمين", value: 72 },
    { label: "إجمالي الطلاب", value: 682 },
    { label: "الأجزاء المحفوظة", value: 139.16 }
  ],

  quickSummary: [
    "إجمالي الطلاب في جميع الحلق: 682 طالبًا",
    "إجمالي الأوجه المحفوظة: 2774.27 وجهًا",
    "إجمالي أوجه المراجعة: 6130.11 وجهًا",
    "إجمالي الأجزاء المحفوظة: 139.16 جزءًا"
  ],

  halaqat: [
    {
      name: "مدرسة الإمام الشافعي ( النموذجية )",
      badge: "الحلق النموذجية",
      halaqCount: 6,
      teachers: 6,
      supervisors: 1,
      students: 45,
      memorizedFaces: 1620,
      memorizedParts: 81,
      reviewFaces: 2348,
      reviewParts: 117,
      broadcastHours: 45,
      minAge: 11,
      maxAge: 24,
      tested: 3,
      passed: 2,
      fullQuran: 1,
      evidenceLink:
        "https://drive.google.com/drive/folders/15ezrN4Cw0o3X8di4HLiSxGiNr8PvNsLW?usp=sharing"
    },

    {
      name: "مدرسة الامام شعبة ( تحفيظ )",
      badge: "حلقات التحفيظ",
      halaqCount: 12,
      teachers: 12,
      supervisors: 1,
      students: "لم يتم الرصد",
      memorizedFaces: "لم يتم الرصد",
      memorizedParts: "لم يتم الرصد",
      reviewFaces: "لم يتم الرصد",
      reviewParts: "لم يتم الرصد",
      broadcastHours: "لم يتم الرصد",
      minAge: "لم يتم الرصد",
      maxAge: "لم يتم الرصد",
      tested: "لم يتم الرصد",
      passed: "لم يتم الرصد",
      fullQuran: "لم يتم الرصد",
      evidenceLink: "لم يتم الرصد"
    },

    {
      name: "مدرسة ابو بكر الصديق رضي الله عنه ( تلقين )",
      badge: "حلقات التلقين",
      halaqCount: 9,
      teachers: 9,
      supervisors: 1,
      students: 106,
      memorizedFaces: 80,
      memorizedParts: 4,
      reviewFaces: 111,
      reviewParts: 5,
      broadcastHours: "لم يتم الرصد",
      minAge: "لم يتم الرصد",
      maxAge: "لم يتم الرصد",
      tested: "لم يتم الرصد",
      passed: "لم يتم الرصد",
      fullQuran: "لم يتم الرصد",
      evidenceLink: "لم يتم الرصد"
    },

    {
      name: "مدرسة الإمام ورش ( تحفيظ )",
      badge: "حلقات التحفيظ",
      halaqCount: 5,
      teachers: 5,
      supervisors: 1,
      students: 56,
      memorizedFaces: 225.27,
      memorizedParts: 11.26,
      reviewFaces: 537.11,
      reviewParts: 26.86,
      broadcastHours: "لم يتم الرصد",
      minAge: 8,
      maxAge: 56,
      tested: "لم يتم الرصد",
      passed: "لم يتم الرصد",
      fullQuran: "لم يتم الرصد",
      evidenceLink:
        "https://drive.google.com/drive/folders/1Xws3Q-YfnoZtOOK99AKN13INHdH_gW11"
    },

    {
      name: "مدرسة الإمام أحمد بن حنبل ( تحفيظ )",
      badge: "حلقات التحفيظ",
      halaqCount: 2,
      teachers: 2,
      supervisors: 1,
      students: 22,
      memorizedFaces: 168,
      memorizedParts: 8.5,
      reviewFaces: 140,
      reviewParts: 7,
      broadcastHours: "لم يتم الرصد",
      minAge: 7,
      maxAge: 55,
      tested: "لم يتم الرصد",
      passed: "لم يتم الرصد",
      fullQuran: "لم يتم الرصد",
      evidenceLink: "لم يتم الرصد"
    },

    {
      name: "مدرسة الإمام حفص ( تحفيظ )",
      badge: "حلقات التحفيظ",
      halaqCount: 16,
      teachers: 16,
      supervisors: 1,
      students: 191,
      memorizedFaces: 182,
      memorizedParts: 9,
      reviewFaces: 545,
      reviewParts: 27,
      broadcastHours: "لم يتم الرصد",
      minAge: "لم يتم الرصد",
      maxAge: "لم يتم الرصد",
      tested: "لم يتم الرصد",
      passed: "لم يتم الرصد",
      fullQuran: "لم يتم الرصد",
      evidenceLink: "لم يتم الرصد"
    },

    {
      name: "مدرسة الإمام البخاري ( تحفيظ )",
      badge: "حلقات التحفيظ",
      halaqCount: 14,
      teachers: 14,
      supervisors: 1,
      students: 153,
      memorizedFaces: 419,
      memorizedParts: 21,
      reviewFaces: 2430,
      reviewParts: 122,
      broadcastHours: "لم يتم الرصد",
      minAge: 8,
      maxAge: 60,
      tested: "لم يتم الرصد",
      passed: "لم يتم الرصد",
      fullQuran: "لم يتم الرصد",
      evidenceLink: "لم يتم الرصد"
    },

    {
      name: "School for non-Arabic speakers",
      badge: "حلق الجاليات",
      halaqCount: 4,
      teachers: 4,
      supervisors: 1,
      students: 41,
      memorizedFaces: 80,
      memorizedParts: 4.4,
      reviewFaces: 19,
      reviewParts: 1,
      broadcastHours: "لم يتم الرصد",
      minAge: 8,
      maxAge: 58,
      tested: "لم يتم الرصد",
      passed: "لم يتم الرصد",
      fullQuran: "لم يتم الرصد",
      evidenceLink: "لم يتم الرصد"
    },

    {
      name: "مدرسة الإمام الشاطبي ( البرامج النوعية )",
      badge: "البرامج النوعية",
      halaqCount: 4,
      teachers: 4,
      supervisors: 1,
      students: 68,
      memorizedFaces: "لم يتم الرصد",
      memorizedParts: "لم يتم الرصد",
      reviewFaces: "لم يتم الرصد",
      reviewParts: "لم يتم الرصد",
      broadcastHours: 9,
      minAge: 8,
      maxAge: 60,
      tested: "لم يتم الرصد",
      passed: "لم يتم الرصد",
      fullQuran: "لم يتم الرصد",
      evidenceLink:
        "https://drive.google.com/drive/folders/1vlEgPCA8iv9lf0lvR9z2-5rp1CvLyexz?usp=drive_link"
    }
  ],

  programs: [
    {
      name: "مساحة إكس",
      beneficiaries: 30,
      broadcastHours: 3,
      evidenceLink:
        "https://x.com/qer_org/status/2053816232554491964?s=46"
    },

    {
      name: "تصحيح التلاوة",
      beneficiaries: 665,
      volunteers: 29,
      broadcastHours: 2,
      volunteerHours: 12,
      evidenceLink: "لم يتم الرصد"
    },

    {
      name: "التجويد",
      beneficiaries: "لم يتم الرصد",
      broadcastHours: 3,
      evidenceLink: "لم يتم الرصد"
    },

    {
      name: "مسابقة رتل",
      students: 24,
      teachers: 2,
      supervisors: 2,
      broadcastHours: 12,
      evidenceLink:
        "https://drive.google.com/drive/folders/1dQ04GYeT8LvDDIksh4ROHPiswx1hbqGA?usp=sharing"
    }
  ],

  tests: {
    tested: 3,
    passed: 2,
    fullQuran: 1
  }
};