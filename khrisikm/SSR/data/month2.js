const DASHBOARD_DATA = {
  title: "إنتاجية التعليم الإلكتروني",
  subtitle: "مؤشرات وبرامج التعليم الإلكتروني",
  note: "عرض مباشر لأبرز مؤشرات التعليم الإلكتروني وبرامجه",
  lastUpdate: "فبراير 2026",
  footerText: "© التعليم الإلكتروني",

  topStats: [
    { label: "إجمالي الحلق", value: 77 },
    { label: "إجمالي المعلمين", value: 77 },
    { label: "إجمالي الطلاب", value: 820 },
    { label: "الأجزاء المحفوظة", value: 1028 }
  ],

  quickSummary: [
    "إجمالي الطلاب في جميع الحلق: 820 طالبًا",
    "إجمالي الأوجه المحفوظة: 13,387 وجهًا",
    "إجمالي أوجه المراجعة: 48,335 وجهًا",
    "أكبر عمر مسجل: 60 سنة",
    "أصغر عمر مسجل: 6 سنوات"
  ],

  halaqat: [
    {
      name: "حلقات التحفيظ",
      badge: "حلقات لتحفيظ القرآن بإتقان للصف الرابع فما فوق",
      halaqCount: 59,
      teachers: 59,
      supervisors: 4,
      students: 636,
      memorizedFaces: 11865,
      reviewFaces: 39300,
      memorizedParts: 949,
      broadcastHours: 2360,
      maxAge: 60,
      minAge: 10
    },
    {
      name: "حلقات التلقين",
      badge: "حلقات للطلاب (5–9 سنوات) لحفظ جزء عمّ وتبارك",
      halaqCount: 8,
      teachers: 7,
      supervisors: 1,
      students: 90,
      memorizedFaces: 370,
      reviewFaces: 620,
      memorizedParts: 22,
      broadcastHours: 320,
      maxAge: 9,
      minAge: 6
    },
    {
      name: "الحلق النموذجية",
      badge: "حلقات للمتميزين لحفظ وجه فأكثر يوميًا",
      halaqCount: 6,
      teachers: 6,
      supervisors: 1,
      students: 49,
      memorizedFaces: 906,
      reviewFaces: 7633,
      memorizedParts: 45,
      broadcastHours: 240,
      maxAge: 24,
      minAge: 11
    },
    {
      name: "حلق الجاليات",
      badge: "حلقات لغير الناطقين بالعربية",
      halaqCount: 4,
      teachers: 3,
      supervisors: 1,
      students: 45,
      memorizedFaces: 246,
      reviewFaces: 782,
      memorizedParts: 12,
      broadcastHours: 160,
      maxAge: 45,
      minAge: 9
    }
  ],

  programs: [
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
    },
    {
      name: "تصحيح التلاوة",
      beneficiaries: 1627,
      volunteers: 69,
      broadcastHours: 9,
      volunteerHours: 40,
      maxAge: 50,
      minAge: 8
    },
    {
      name: "برنامج محاريب",
      participants: 661,
      halaqat: 5,
      reviewParts: 19830,
      teachers: 5,
      supervisors: 2,
      reviewFaces: 396600
    },
    {
      name: "مسابقة رتل",
      participants: 345,
      teachers: 10,
      halaqat: 10
    },
    {
      name: "مساحة إكس",
      beneficiaries: 925,
      broadcastHours: 8
    },
    {
      name: "دورات التجويد",
      beneficiaries: 30,
      broadcastHours: 32,
      maxAge: 62,
      minAge: 9
    },
    {
      name: "ختمة مباركة (قدوات لكبار السن)",
      beneficiaries: 20
    }
  ],

  tests: {
    tested: 135,
    passed: 113,
    fullQuran: 2
  }
};