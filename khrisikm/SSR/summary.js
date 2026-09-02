const DASHBOARD_DATA = {
  title: "إنتاجية التعليم الإلكتروني",
  subtitle: "مؤشرات وبرامج التعليم الإلكتروني",
  note: "الإحصائية التراكمية لجميع الأشهر",
  lastUpdate: "آخر تحديث: إحصائية تراكمية",
  footerText: "© التعليم الإلكتروني",

  topStats: [
    { label: "إجمالي الحلق", value: 77 },
    { label: "إجمالي المعلمين", value: 77 },
    { label: "إجمالي الطلاب", value: 820 },
    { label: "الأجزاء المحفوظة", value: 1439 }
  ],

  quickSummary: [
    "إجمالي الطلاب في جميع الحلق: 820 طالبًا",
    "إجمالي الأوجه المحفوظة: 21,629 وجهًا",
    "إجمالي أوجه المراجعة: 70,113 وجهًا",
    "أكبر عمر مسجل: 70 سنة",
    "أصغر عمر مسجل: 6 سنوات"
  ],

  halaqat: [
    {
      name: "حلقات التحفيظ",
      badge: "إحصائية تراكمية",
      halaqCount: 59,
      teachers: 59,
      supervisors: 4,
      students: 636,
      memorizedFaces: 17390,
      reviewFaces: 52888,
      memorizedParts: 1225,
      broadcastHours: 2360,
      maxAge: 70,
      minAge: 10
    },
    {
      name: "حلقات التلقين",
      badge: "إحصائية تراكمية",
      halaqCount: 8,
      teachers: 8,
      supervisors: 1,
      students: 90,
      memorizedFaces: 1105,
      reviewFaces: 1275,
      memorizedParts: 58,
      broadcastHours: 320,
      maxAge: 9,
      minAge: 6
    },
    {
      name: "الحلق النموذجية",
      badge: "إحصائية تراكمية",
      halaqCount: 6,
      teachers: 6,
      supervisors: 1,
      students: 49,
      memorizedFaces: 1706,
      reviewFaces: 14885,
      memorizedParts: 85,
      broadcastHours: 240,
      maxAge: 24,
      minAge: 10
    },
    {
      name: "حلق الجاليات",
      badge: "إحصائية تراكمية",
      halaqCount: 4,
      teachers: 4,
      supervisors: 1,
      students: 45,
      memorizedFaces: 1428,
      reviewFaces: 1065,
      memorizedParts: 71,
      broadcastHours: 160,
      maxAge: 65,
      minAge: 9
    }
  ],

  programs: [
    {
      name: "تصحيح التلاوة",
      beneficiaries: 1722,
      volunteers: 74,
      broadcastHours: 18,
      volunteerHours: 45,
      maxAge: 55,
      minAge: 7
    },
    {
      name: "التجويد",
      beneficiaries: 178,
      volunteers: 7,
      broadcastHours: 39,
      volunteerHours: 7,
      maxAge: 65,
      minAge: 9
    },
    {
      name: "تحفة الأطفال",
      beneficiaries: 15
    },
    {
      name: "ختمة مباركة (قدوات لكبار السن)",
      beneficiaries: 20
    },
    {
      name: "مساحة إكس",
      beneficiaries: 307,
      broadcastHours: 16
    },
    {
      name: "مسابقة رتل",
      participants: 345,
      teachers: 10,
      halaqat: 10
    },
    {
      name: "البوث الرمضاني بنادي القادسية",
      visitors: 4889,
      beneficiaries: 2892,
      volunteers: 15,
      broadcastHours: 52,
      volunteerHours: 60,
      dailyDetails: [
        { day: "الثلاثاء", date: "24/02/2026", visitors: 225, beneficiaries: 144, hours: 4 },
        { day: "الأربعاء", date: "25/02/2026", visitors: 270, beneficiaries: 130, hours: 4 },
        { day: "الخميس", date: "26/02/2026", visitors: 380, beneficiaries: 224, hours: 4 },
        { day: "الجمعة", date: "27/02/2026", visitors: 436, beneficiaries: 267, hours: 4 },
        { day: "السبت", date: "28/02/2026", visitors: 390, beneficiaries: 241, hours: 4 },
        { day: "الأحد", date: "01/03/2026", visitors: 408, beneficiaries: 263, hours: 4 },
        { day: "الاثنين", date: "02/03/2026", visitors: 290, beneficiaries: 185, hours: 4 },
        { day: "الثلاثاء", date: "03/03/2026", visitors: 255, beneficiaries: 180, hours: 4 },
        { day: "الأربعاء", date: "04/03/2026", visitors: 452, beneficiaries: 293, hours: 4 },
        { day: "الخميس", date: "05/03/2026", visitors: 414, beneficiaries: 217, hours: 4 },
        { day: "الجمعة", date: "06/03/2026", visitors: 532, beneficiaries: 291, hours: 4 },
        { day: "السبت", date: "07/03/2026", visitors: 426, beneficiaries: 254, hours: 4 },
        { day: "الأحد", date: "08/03/2026", visitors: 411, beneficiaries: 203, hours: 4 }
      ]
    }
  ],

  tests: {
    tested: 255,
    passed: 223,
    fullQuran: 4
  }
};