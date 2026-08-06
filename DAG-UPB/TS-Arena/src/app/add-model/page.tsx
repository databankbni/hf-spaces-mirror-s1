import Breadcrumbs from '@/src/components/Breadcrumbs';
import { Mail, Key, TrendingUp, Trophy, BarChart3, Users, CheckCircle, UserPlus } from 'lucide-react';
import { siGithub } from 'simple-icons/icons';
import { getConsoleUrl } from '@/src/config/console';

export default function InfoPage() {
  // With a console, signing up is self-service and the email address is only
  // there for people who get stuck. Without one — a fork that does not run
  // the console — the email route is the only way in, so it stays primary.
  const consoleUrl = getConsoleUrl();

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Breadcrumbs items={[{ label: 'Add Model', href: '/add-model' }]} />
      
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Join the TS-Arena Benchmark</h1>
        <p className="mt-2 text-gray-600">
          Test your forecasting models against the best in real-time benchmark challenges
        </p>
      </div>

      {/* Main CTA Section */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200 p-4 sm:p-6 mb-8">
        <h2 className="text-xl font-semibold text-gray-900 mb-3">Get Started</h2>
        <p className="text-gray-700 mb-4">
          Ready to test your forecasting models against the best? Participate actively in our benchmark challenges!{' '}
          {consoleUrl
            ? 'Create an account in the console and mint your own API key.'
            : 'Simply send us an email and we’ll provide you with an API key to get started.'}{' '}
          Find detailed participation instructions in our{' '}
          <a
            href="https://github.com/DAG-UPB/ts-arena"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-700 hover:text-blue-900 font-semibold underline"
          >
            Git repository
          </a>.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {consoleUrl ? (
                  <a
                    href={`${consoleUrl}/register`}
                    className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-colors shadow-sm"
                  >
                    <UserPlus className="w-5 h-5" />
                    Create an Account
                  </a>
                ) : (
                  <a
                    href="mailto:DataAnalytics@wiwi.uni-paderborn.de?subject=TS-Arena API Key Request&body=Hello,%0D%0A%0D%0AI would like to participate in the TS-Arena benchmark.%0D%0A%0D%0AOrganization: [Please specify your organization]%0D%0A%0D%0ABest regards"
                    className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-colors shadow-sm"
                  >
                    <Mail className="w-5 h-5" />
                    Request API Key
                  </a>
                )}
                <a
                  href="mailto:DataAnalytics@wiwi.uni-paderborn.de?subject=TS-Arena Questions&body=Hello,%0D%0A%0D%0AI have questions about participating in the TS-Arena benchmark.%0D%0A%0D%0ABest regards"
                  className="inline-flex items-center justify-center gap-2 px-6 py-3 bg-white hover:bg-gray-50 text-gray-900 font-semibold rounded-lg border border-gray-300 transition-colors shadow-sm"
                >
                  <Mail className="w-5 h-5" />
                  Ask Questions
                </a>
              </div>

        {consoleUrl && (
          <p className="mt-4 text-sm text-gray-600">
            Already have an account?{' '}
            <a href={`${consoleUrl}/login`} className="text-blue-700 hover:text-blue-900 font-semibold underline">
              Sign in to the console
            </a>
            . If you would rather not manage an account, write to us and we will set you up.
          </p>
        )}
      </div>

      {/* How it Works */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 sm:p-6 mb-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">How it Works</h2>
        <div className="space-y-4 text-gray-700">
          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center font-semibold">
              1
            </div>
            <div>
              {consoleUrl ? (
                <>
                  <h3 className="font-medium text-gray-900 mb-1">Create an Account and an API Key</h3>
                  <p className="text-sm text-gray-600">
                    Register in the{' '}
                    <a href={`${consoleUrl}/register`} className="text-blue-700 hover:text-blue-900 underline">
                      console
                    </a>
                    , confirm your email address, then mint an API key there. Naming an organization
                    creates it with you as its admin and shows it on the leaderboard; leave it blank to
                    take part as an individual. If your organization already exists, ask its admin to
                    invite you instead.
                  </p>
                </>
              ) : (
                <>
                  <h3 className="font-medium text-gray-900 mb-1">Request an API Key</h3>
                  <p className="text-sm text-gray-600">
                    Email us with your organization name and we&apos;ll send you an API key.
                  </p>
                </>
              )}
            </div>
          </div>
          
          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center font-semibold">
              2
            </div>
            <div>
              <h3 className="font-medium text-gray-900 mb-1">Register Your Model</h3>
              <p className="text-sm text-gray-600">
                Use your API key to register models for challenges in the registration phase.
              </p>
            </div>
          </div>
          
          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center font-semibold">
              3
            </div>
            <div>
              <h3 className="font-medium text-gray-900 mb-1">Submit Forecasts</h3>
              <p className="text-sm text-gray-600">
                Obtain time-series context via our API and submit your forecasts before registration closes.
                Every forecast is committed before the values it predicts exist, which is what makes
                leakage impossible here.
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center font-semibold">
              4
            </div>
            <div>
              <h3 className="font-medium text-gray-900 mb-1">Wait for the Ground Truth</h3>
              <p className="text-sm text-gray-600">
                Once registration closes, no further forecasts are accepted for that round. The round then
                plays out on live data, and nothing can be scored until every real value it covers has
                arrived. For a long horizon that wait is the length of the horizon itself.
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center font-semibold">
              5
            </div>
            <div>
              <h3 className="font-medium text-gray-900 mb-1">Evaluation</h3>
              <p className="text-sm text-gray-600">
                When the ground truth for a round is complete, your forecast is scored automatically. The
                check runs every 30 minutes, so results follow shortly after the last value lands rather
                than the moment it does. The error metrics themselves are in the code on{' '}
                <a
                  href="https://github.com/DAG-UPB/ts-arena"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-700 hover:text-blue-900 underline"
                >
                  GitHub
                </a>
                .
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="flex-shrink-0 w-8 h-8 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center font-semibold">
              6
            </div>
            <div>
              <h3 className="font-medium text-gray-900 mb-1">Where You Appear</h3>
              <p className="text-sm text-gray-600">
                A scored model shows up in that challenge&apos;s leaderboard and in the aggregate views
                (domain, category, frequency). The overall ranking is stricter: a model enters it only once
                it has taken part in every challenge, and in at least half of each challenge&apos;s rounds
                since it joined, so nobody gains by covering only the challenges that suit them. Rankings
                are recomputed four times a day. You can follow your model on the leaderboards and inspect
                individual forecasts in the interactive plots.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Benefits Grid */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 sm:p-6 mb-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">What You Get</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="flex gap-3">
            <Key className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-medium text-gray-900">Personal API Key</h3>
              <p className="text-sm text-gray-600">For model registration and submission</p>
            </div>
          </div>
          
          <div className="flex gap-3">
            <BarChart3 className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-medium text-gray-900">Benchmark Datasets</h3>
              <p className="text-sm text-gray-600">Access to datasets and challenge specifications</p>
            </div>
          </div>
          
          <div className="flex gap-3">
            <Trophy className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-medium text-gray-900">Rankings & Leaderboards</h3>
              <p className="text-sm text-gray-600">Real-time performance tracking</p>
            </div>
          </div>
          
          <div className="flex gap-3">
            <TrendingUp className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-medium text-gray-900">Detailed Metrics</h3>
              <p className="text-sm text-gray-600">Comprehensive evaluation across time series</p>
            </div>
          </div>
          
          <div className="flex gap-3">
            <Users className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-medium text-gray-900">Community Support</h3>
              <p className="text-sm text-gray-600">Connect with forecasting researchers</p>
            </div>
          </div>
        </div>
      </div>

      {/* Requirements */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 sm:p-6 mb-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Requirements</h2>
        <div className="space-y-2">
          <div className="flex gap-2 items-start">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            {/* An organization is optional in the console — individuals take part too,
                so this must not read as a hard requirement any more. */}
            <span className="text-gray-700">
              {consoleUrl
                ? 'A verified email address; an organization is optional'
                : 'Valid organization or affiliation'}
            </span>
          </div>
          <div className="flex gap-2 items-start">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <span className="text-gray-700">Commitment to fair participation</span>
          </div>
          <div className="flex gap-2 items-start">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <span className="text-gray-700">Adherence to benchmark guidelines</span>
          </div>
        </div>
      </div>

      {/* Model Validation Section */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 sm:p-6">
        <div className="flex items-start gap-3 mb-4">
          <svg role="img" viewBox="0 0 24 24" className="w-6 h-6 text-gray-900 flex-shrink-0 mt-1 fill-current" xmlns="http://www.w3.org/2000/svg">
            <path d={siGithub.path} />
          </svg>
          <div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Help Us Validate Model Implementations</h2>
            <p className="text-gray-700">
              Transparency is at the heart of our live benchmarking project. We have integrated a wide range of 
              state-of-the-art time series forecasting models to provide the community with real-time performance insights.
            </p>
          </div>
        </div>
        
        <div className="bg-gray-50 rounded-lg p-4 mb-4">
          <p className="text-gray-700 mb-3">
            To ensure that every model is evaluated under optimal conditions, <strong>we invite the original authors 
            and maintainers to review our implementations.</strong> If you are a developer of one of the featured models, 
            we would value your feedback on:
          </p>
          <ul className="space-y-2 ml-4">
            <li className="flex gap-2 items-start text-gray-700">
              <span className="text-blue-600 font-bold">•</span>
              <span>Model configuration and hyperparameters</span>
            </li>
            <li className="flex gap-2 items-start text-gray-700">
              <span className="text-blue-600 font-bold">•</span>
              <span>Data preprocessing steps</span>
            </li>
            <li className="flex gap-2 items-start text-gray-700">
              <span className="text-blue-600 font-bold">•</span>
              <span>Implementation-specific nuances</span>
            </li>
          </ul>
        </div>
        
        <p className="text-gray-700 mb-4">
          Our goal is to represent your work as accurately as possible. Please visit our GitHub repository 
          to review the code or open an issue for any suggested improvements.
        </p>
        
        <a 
          href="https://github.com/DAG-UPB/ts-arena" 
          target="_blank" 
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 bg-gray-900 hover:bg-gray-800 text-white font-medium rounded-lg transition-colors"
        >
          <svg role="img" viewBox="0 0 24 24" className="w-5 h-5 fill-current" xmlns="http://www.w3.org/2000/svg">
            <path d={siGithub.path} />
          </svg>
          View on GitHub
        </a>
      </div>
    </div>
  );
}
