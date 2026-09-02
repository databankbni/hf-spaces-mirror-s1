import Breadcrumbs from '@/src/components/Breadcrumbs';
import { BookOpen, ExternalLink, CheckCircle } from 'lucide-react';
import { siHuggingface } from 'simple-icons/icons';

const HF_DATASET_URL = 'https://huggingface.co/datasets/DAG-UPB/TS-Arena-Archive';

const CITATION = `@inproceedings{meyer2026tsarena,
  title={TS-Arena -- A Live Forecast Pre-Registration Platform},
  author={Marcel Meyer and Sascha Kaltenpoth and Henrik Albers and Kevin Zalipski and Oliver Müller},
  booktitle={Proceedings of the 32nd ACM SIGKDD Conference on Knowledge Discovery and Data Mining V.2},
  series={KDD '26},
  pages={9558--9568},
  year={2026},
  publisher={Association for Computing Machinery},
  doi={10.1145/3770855.3817515},
  url={https://doi.org/10.1145/3770855.3817515},
}`;

export default function BacktestingArchivePage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Breadcrumbs items={[{ label: 'Backtesting Archive', href: '/backtesting-archive' }]} />

        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Backtesting Archive</h1>
          <p className="mt-2 text-gray-600">
            Offline evaluation snapshots for fast model benchmarking without running live challenges.
          </p>
        </div>

        {/* CTA */}
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200 p-4 sm:p-6 mb-6">
          <p className="text-gray-700 mb-4">
            The archive provides quarterly snapshots of past challenges, including input context,
            ground truth, and the pre-registered forecasts from all participating models. This lets
            you evaluate a new model offline and report results in a paper, e.g.{' '}
            <em>&quot;evaluated on TS-Arena Archive Q1 2026&quot;</em>.
          </p>
          <a
            href={HF_DATASET_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition-colors shadow-sm"
          >
            <svg role="img" viewBox="0 0 24 24" className="w-5 h-5 fill-current" xmlns="http://www.w3.org/2000/svg">
              <path d={siHuggingface.path} />
            </svg>
            Open on Hugging Face
            <ExternalLink className="w-4 h-4" />
          </a>
        </div>

        {/* Usage Guidelines */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 sm:p-8 mb-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Usage Guidelines</h2>
          <div className="space-y-3">
            <div className="flex gap-2 items-start">
              <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-gray-700">
                <span className="font-semibold text-gray-900">Temporal split.</span> Use a training
                cutoff strictly before the start of the evaluation period to prevent data leakage.
              </p>
            </div>
            <div className="flex gap-2 items-start">
              <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-gray-700">
                <span className="font-semibold text-gray-900">Self-reported results.</span> Clearly
                state that results are based on the TS-Arena Archive and are not official rankings
                from the TS-Arena platform.
              </p>
            </div>
            <div className="flex gap-2 items-start">
              <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-gray-700">
                <span className="font-semibold text-gray-900">Official leaderboard.</span> Inclusion
                in the live rankings and future archive dumps requires participation in challenges at{' '}
                <a href="https://ts-arena.live" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-800 underline">
                  ts-arena.live
                </a>
                .
              </p>
            </div>
          </div>
        </div>

        {/* Citation */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 sm:p-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-3">Citation</h2>
          <pre className="bg-gray-900 text-gray-100 text-xs rounded-md p-4 overflow-x-auto mb-4">
            <code>{CITATION}</code>
          </pre>
          <a
            href="https://doi.org/10.1145/3770855.3817515"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
          >
            <BookOpen className="w-4 h-4" />
            Read in the ACM Digital Library
          </a>
        </div>
      </div>
    </div>
  );
}
