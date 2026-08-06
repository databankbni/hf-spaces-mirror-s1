import Image from 'next/image';
import Breadcrumbs from '@/src/components/Breadcrumbs';
import { BookOpen, Users, FlaskConical, BarChart3, Linkedin, GraduationCap } from 'lucide-react';

type TeamMember = {
  name: string;
  role?: string;
  photo: string;
  linkedin?: string;
  university: string;
};

const TEAM: TeamMember[] = [
  {
    name: 'Marcel Meyer',
    photo: '/team/marcel.png',
    linkedin: 'https://www.linkedin.com/in/profil-marcel-meyer/',
    university: 'https://www.uni-paderborn.de/person/105120',
  },
  {
    name: 'Sascha Kaltenpoth',
    photo: '/team/sascha.png',
    linkedin: 'https://www.linkedin.com/in/sascha-kaltenpoth-727123214/',
    university: 'https://www.uni-paderborn.de/person/50640',
  },
  {
    name: 'Henrik Albers',
    photo: '/team/henrik.png',
    linkedin: 'https://www.linkedin.com/in/henrik-albers/',
    university: 'https://www.uni-paderborn.de/person/57403',
  },
  {
    name: 'Kevin Zalipski',
    photo: '/team/kevin.png',
    university: 'https://www.uni-paderborn.de/person/62222',
  },
  {
    name: 'Prof. Dr. Oliver Müller',
    role: 'Head of Data Analytics Group',
    photo: '/team/oliver.png',
    linkedin: 'https://www.linkedin.com/in/oliver-m%C3%BCller-5ba83240/',
    university: 'https://www.uni-paderborn.de/person/72849',
  },
];

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Breadcrumbs items={[{ label: 'About', href: '/about' }]} />

        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">About TS-Arena</h1>
          <p className="mt-2 text-gray-600">
            A live benchmarking platform for Time Series Foundation Models using forecast pre-registration.
          </p>
        </div>

        {/* Paper Section */}
        <div className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8 mb-6">
          <div className="flex items-center gap-3 mb-4">
            <BookOpen className="w-6 h-6 text-blue-600 flex-shrink-0" />
            <h2 className="text-xl font-semibold text-gray-900">Research Paper</h2>
          </div>

          <div className="mb-4">
            <h3 className="text-lg font-medium text-gray-900 mb-1">
              TS-Arena: A Live Forecast Pre-Registration Platform
            </h3>
            <p className="text-sm text-gray-500">
              Marcel Meyer, Sascha Kaltenpoth, Henrik Albers, Kevin Zalipski, Oliver Müller &mdash; Paderborn University, Data Analytics Group, 2026
            </p>
          </div>

          <div className="bg-gray-50 rounded-md p-4 mb-5 text-sm text-gray-700 leading-relaxed border border-gray-200">
            <span className="font-semibold text-gray-800">Abstract. </span>
            TS-Arena is a live benchmarking platform that evaluates Time Series Foundation Models (TSFMs) by
            requiring forecast submissions <em>before</em> ground-truth data exists — a &ldquo;forecast
            pre-registration protocol.&rdquo; This design eliminates test-set contamination and information
            leakage, since the evaluation target physically does not exist at submission time. The platform
            continuously collects forecasts from models across 186 energy-sector time series in 14 challenge
            definitions, scores them with MASE, and ranks them using an ELO rating system with confidence
            intervals.
          </div>

          <a
            href="https://arxiv.org/abs/2512.20761"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
          >
            <BookOpen className="w-4 h-4" />
            Read on arXiv
          </a>
        </div>

        <div className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8 mb-6">
          <div className="flex items-center gap-3 mb-4">
            <BookOpen className="w-6 h-6 text-blue-600 flex-shrink-0" />
            <h2 className="text-xl font-semibold text-gray-900">2025 Technical Report</h2>
          </div>

          <div className="mb-4">
            <h3 className="text-lg font-medium text-gray-900 mb-1">
              TS-Arena Technical Report -- A Pre-registered Live Forecasting Platform
            </h3>
            <p className="text-sm text-gray-500">
              Marcel Meyer, Sascha Kaltenpoth, Kevin Zalipski, Henrik Albers, Oliver Müller &mdash; Paderborn University, Data Analytics Group, 2025
            </p>
          </div>

          <div className="bg-gray-50 rounded-md p-4 mb-5 text-sm text-gray-700 leading-relaxed border border-gray-200">
            <span className="font-semibold text-gray-800">Abstract. </span>
            While Time Series Foundation Models (TSFMs) offer transformative capabilities for forecasting, they simultaneously risk triggering a fundamental evaluation crisis. This crisis is driven by information leakage due to overlapping training and test sets across different models, as well as the illegitimate transfer of global patterns to test data. While the ability to learn shared temporal dynamics represents a primary strength of these models, their evaluation on historical archives often permits the exploitation of observed global shocks, which violates the independence required for valid benchmarking. We introduce TS-Arena, a platform that restores the operational integrity of forecasting by treating the genuinely unknown future as the definitive test environment. By implementing a pre-registration mechanism on live data streams, the platform ensures that evaluation targets remain physically non-existent during inference, thereby enforcing a strict global temporal split. This methodology establishes a moving temporal frontier that prevents historical contamination and provides an authentic assessment of model generalization. Initially applied within the energy sector, TS-Arena provides a sustainable infrastructure for comparing foundation models under real-world constraints. A prototype of the platform is available at this https URL. 
          </div>

          <a
            href="https://arxiv.org/abs/2512.20761v1"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
          >
            <BookOpen className="w-4 h-4" />
            Read on arXiv
          </a>
        </div>

        {/* Platform Overview */}
        <div className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8 mb-6">
          <div className="flex items-center gap-3 mb-4">
            <FlaskConical className="w-6 h-6 text-blue-600 flex-shrink-0" />
            <h2 className="text-xl font-semibold text-gray-900">How It Works</h2>
          </div>
          <p className="text-gray-700 text-sm leading-relaxed mb-4">
            TS-Arena runs continuously scheduled forecasting challenges on real-world energy data. When a new
            challenge round opens, models have a registration window to submit their forecasts for a future
            time period. Once the ground truth becomes available, submitted forecasts are automatically
            evaluated and rankings are updated.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-gray-50 rounded-md p-4 border border-gray-200">
              <div className="font-semibold text-gray-800 text-sm mb-1">Pre-Registration</div>
              <p className="text-xs text-gray-600">Forecasts must be submitted before ground truth exists, making data leakage structurally impossible.</p>
            </div>
            <div className="bg-gray-50 rounded-md p-4 border border-gray-200">
              <div className="font-semibold text-gray-800 text-sm mb-1">MASE Scoring</div>
              <p className="text-xs text-gray-600">Mean Absolute Scaled Error provides scale-independent accuracy scores comparable across time series.</p>
            </div>
            <div className="bg-gray-50 rounded-md p-4 border border-gray-200">
              <div className="font-semibold text-gray-800 text-sm mb-1">ELO Ranking</div>
              <p className="text-xs text-gray-600">Pairwise ELO ratings with confidence intervals enable fair comparison between models over time.</p>
            </div>
          </div>
        </div>

        {/* Data */}
        <div className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8 mb-6">
          <div className="flex items-center gap-3 mb-4">
            <BarChart3 className="w-6 h-6 text-blue-600 flex-shrink-0" />
            <h2 className="text-xl font-semibold text-gray-900">Data & Challenges</h2>
          </div>
          <p className="text-gray-700 text-sm leading-relaxed">
            The benchmark covers 186 energy-sector time series from multiple European and North American grid
            operators (SMARD, EIA, Fingrid, ENTSO-E, GridStatus), organized into 14 challenge definitions with
            varying forecast frequencies (15 min, 1 h) and horizons (1 day, 1 week). Challenges span
            electricity consumption and generation, providing diverse conditions for a thorough model
            evaluation.
          </p>
        </div>

        {/* Contact */}
        <div id="contact" className="bg-white shadow-sm rounded-lg border border-gray-200 p-6 sm:p-8 scroll-mt-24">
          <div className="flex items-center gap-3 mb-4">
            <Users className="w-6 h-6 text-blue-600 flex-shrink-0" />
            <h2 className="text-xl font-semibold text-gray-900">Contact</h2>
          </div>
          <p className="text-gray-700 text-sm leading-relaxed mb-4">
            TS-Arena is developed by the{' '}
            <a
              href="https://go.upb.de/data-analytics"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:text-blue-800 underline"
            >
              Data Analytics Group
            </a>{' '}
            at Paderborn University, Germany. We are open to collaboration, for example to integrate
            additional live time series into TS-Arena. Feel free to reach out to any of us directly
            or write to{' '}
            <a
              href="mailto:DataAnalytics@wiwi.uni-paderborn.de"
              className="text-blue-600 hover:text-blue-800 underline"
            >
              DataAnalytics@wiwi.uni-paderborn.de
            </a>
            .
          </p>

          <div className="flex flex-wrap justify-center gap-4 mt-6">
            {TEAM.map((member) => (
              <div
                key={member.name}
                className="flex flex-col items-center text-center bg-gray-50 rounded-md p-5 border border-gray-200 w-full sm:w-[calc(50%-0.5rem)] lg:w-[calc(33.333%-0.75rem)]"
              >
                <div className="relative w-24 h-24 rounded-full overflow-hidden border border-gray-200 bg-white mb-3">
                  <Image
                    src={member.photo}
                    alt={member.name}
                    fill
                    sizes="96px"
                    className="object-cover"
                  />
                </div>
                <div className="font-semibold text-gray-900 text-sm">{member.name}</div>
                {member.role && (
                  <div className="text-xs text-gray-500 mb-3">{member.role}</div>
                )}
                <div className="flex items-center gap-2 mt-3">
                  {member.linkedin && (
                    <a
                      href={member.linkedin}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`${member.name} on LinkedIn`}
                      className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-white border border-gray-200 text-gray-600 hover:text-blue-600 hover:border-blue-300 transition-colors"
                    >
                      <Linkedin className="w-4 h-4" />
                    </a>
                  )}
                  <a
                    href={member.university}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${member.name} at Paderborn University`}
                    className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-white border border-gray-200 text-gray-600 hover:text-blue-600 hover:border-blue-300 transition-colors"
                  >
                    <GraduationCap className="w-4 h-4" />
                  </a>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
