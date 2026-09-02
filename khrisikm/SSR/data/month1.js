const DASHBOARD_DATA = {
  title: "إنتاجية التعليم الإلكتروني",
  subtitle: "مؤشرات وبرامج التعليم الإلكتروني",
  note: "عرض مباشر لأبرز مؤشرات التعليم الإلكتروني وبرامجه",
  lastUpdate: "إنتاجية شهر 1",
  footerText: "© التعليم الإلكتروني",

  topStats: [
    { label: "إجمالي الحلق", value: 67 },
    { label: "إجمالي المعلمين", value: 67 },
    { label: "إجمالي الطلاب", value: 708 },
    { label: "الأجزاء المحفوظة", value: 411 }
  ],

  quickSummary: [
    "إجمالي الطلاب في جميع الحلق: 708 طالبًا",
    "إجمالي الأوجه المحفوظة: 8,242 وجهًا",
    "إجمالي أوجه المراجعة: 21,778 وجهًا",
    "أكبر عمر مسجل: 70 سنة",
    "أصغر عمر مسجل: 7 سنوات"
  ],

  halaqat: [
    {
      name: "حلقات التحفيظ",
      halaqCount: 50,
      teachers: 50,
      students: 537,
      memorizedFaces: 5525,
      reviewFaces: 13588,
      memorizedParts: 276,
      maxAge: 70,
      minAge: 10
    },
    {
      name: "حلقات التلقين",
      halaqCount: 8,
      teachers: 8,
      students: 84,
      memorizedFaces: 735,
      reviewFaces: 655,
      memorizedParts: 36,
      maxAge: 9,
      minAge: 7
    },
    {
      name: "الحلق النموذجية",
      halaqCount: 5,
      teachers: 5,
      students: 44,
      memorizedFaces: 800,
      reviewFaces: 7252,
      memorizedParts: 40,
      maxAge: 23,
      minAge: 10
    },
    {
      name: "حلق الجاليات",
      halaqCount: 4,
      teachers: 4,
      students: 43,
      memorizedFaces: 1182,
      reviewFaces: 283,
      memorizedParts: 59,
      maxAge: 65,
      minAge: 9
    }
  ],

  programs: [
    {
      name: "تصحيح التلاوة",
      beneficiaries: 95,
      volunteers: 5,
      broadcastHours: 9,
      volunteerHours: 5,
      maxAge: 55,
      minAge: 7
    },
    {
      name: "دورات التجويد",
      beneficiaries: 30,
      broadcastHours: 32,
      maxAge: 62,
      minAge: 9
    },
    {
      name: "مساحة إكس",
      beneficiaries: 824,
      broadcastHours: 8
    }
  ],

  tests: {
    tested: 120,
    passed: 110,
    fullQuran: 1
  }
};