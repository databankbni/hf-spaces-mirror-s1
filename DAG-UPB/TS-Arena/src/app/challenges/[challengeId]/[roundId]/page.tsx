'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Breadcrumbs from '@/src/components/Breadcrumbs';
import TimeSeriesChart from '@/src/components/TimeSeriesChart';
import LeaderBoardRound from '@/src/components/LeaderBoardRound';
import Link from 'next/link';
import { Clock, ChevronRight, Info } from 'lucide-react';

interface RoundMetadata {
  round_id: number;
  name: string;
  description: string;
  status: string;
  context_length: number;
  horizon: string;
  start_time: string;
  end_time: string;
  registration_start: string;
  registration_end: string;
  frequency?: string;
}

interface LeaderboardEntry {
  model_id: number;
  readable_id: string;
  model_name: string;
  series_id: number;
  series_name: string;
  forecast_count: number;
  mase: number | null;
  rmse: number | null;
  is_final: boolean;
  rank: number;
}

export default function RoundDetail() {
  const params = useParams();
  const router = useRouter();
  const challengeId = params.challengeId;
  const [round, setRound] = useState<RoundMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [leaderboardLoading, setLeaderboardLoading] = useState(false);

  useEffect(() => {
    const fetchRound = async () => {
      // Handle params.roundId which can be string | string[] | undefined
      const roundIdParam = params.roundId;
      if (!roundIdParam) {
        setError('Invalid round ID: undefined');
        setLoading(false);
        return;
      }

      const roundId = Array.isArray(roundIdParam) ? roundIdParam[0] : roundIdParam;
      
      try {
        setLoading(true);
        setError(null);

        // Fetch the round data using the rounds endpoint
        const response = await fetch(`/api/v1/rounds/${roundId}`);
        
        if (!response.ok) {
          throw new Error('Failed to fetch round data');
        }
        
        const data: RoundMetadata = await response.json();
        setRound(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
        console.error('Error fetching round:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchRound();
  }, [params.roundId]);

  // Fetch leaderboard data
  useEffect(() => {
    const fetchLeaderboard = async () => {
      const roundIdParam = params.roundId;
      if (!roundIdParam) return;

      const roundId = Array.isArray(roundIdParam) ? roundIdParam[0] : roundIdParam;
      
      try {
        setLeaderboardLoading(true);
        const response = await fetch(`/api/v1/rounds/${roundId}/leaderboard`);
        
        if (!response.ok) {
          console.error('Failed to fetch leaderboard');
          return;
        }
        
        const data: LeaderboardEntry[] = await response.json();
        setLeaderboard(data);
      } catch (err) {
        console.error('Error fetching leaderboard:', err);
      } finally {
        setLeaderboardLoading(false);
      }
    };

    fetchLeaderboard();
  }, [params.roundId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 p-4 sm:p-6">
        <div className="max-w-7xl mx-auto">
          <div className="flex justify-center items-center h-64">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
          </div>
        </div>
      </div>
    );
  }

  if (error || !round) {
    return (
      <div className="min-h-screen bg-gray-50 p-4 sm:p-6">
        <div className="max-w-7xl mx-auto">
          <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded">
            <p className="font-semibold">Error</p>
            <p className="text-sm">{error || 'Round not found'}</p>
          </div>
          <button
            onClick={() => router.back()}
            className="mt-4 text-blue-600 hover:text-blue-800 text-sm font-medium"
          >
            ← Go back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-4 sm:p-6">
      <div className="max-w-7xl mx-auto">
        <Breadcrumbs 
          items={[
            { label: 'Challenges', href: '/challenges' },
            { label: `Challenge #${challengeId}`, href: `/challenges/${challengeId}` },
            { label: `Round #${params.roundId || ''}`, href: `/challenges/${challengeId}/${params.roundId}` }
          ]} 
        />
        
        <header className="mb-8">
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                {round.name || `Round ${params.roundId}`}
              </h1>
              {round.description && (
                <p className="text-gray-600 mt-2">{round.description}</p>
              )}
            </div>
            {round.status && (
              <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
                round.status === 'active' 
                  ? 'bg-green-100 text-green-800'
                  : round.status === 'completed'
                  ? 'bg-blue-100 text-blue-800'
                  : round.status === 'registration'
                  ? 'bg-yellow-100 text-yellow-800'
                  : 'bg-gray-100 text-gray-800'
              }`}>
                {round.status.charAt(0).toUpperCase() + round.status.slice(1)}
              </span>
            )}
          </div>
        </header>

        {/* Registration Banner */}
        {round.status === 'registration' && (
          <Link 
            href="/add-model"
            className="mb-6 bg-yellow-50 border border-yellow-200 rounded-lg px-4 sm:px-6 py-4 block hover:bg-yellow-100 hover:border-yellow-300 transition-colors cursor-pointer"
          >
            <div className="flex items-center">
              <Clock className="h-6 w-6 text-yellow-600 mr-3 flex-shrink-0" />
              <div>
                <p className="text-yellow-800 font-medium">
                  Registration is open — submit your forecasts by{' '}
                  <span className="font-semibold">
                    {round.registration_end 
                      ? new Date(round.registration_end).toLocaleDateString('en-US', {
                          weekday: 'long',
                          year: 'numeric',
                          month: 'long',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                          timeZoneName: 'short'
                        })
                      : 'the registration deadline'}
                  </span>
                </p>
              </div>
              <ChevronRight className="h-5 w-5 text-yellow-600 ml-auto flex-shrink-0" />
            </div>
          </Link>
        )}

        {/* Time Series Chart Section */}
        {round.status === 'registration' ? (
          <div className="bg-white rounded-lg shadow-md overflow-hidden mb-8">
            <div className="px-4 sm:px-6 py-4 bg-gray-50 border-b border-gray-200">
              <h2 className="text-xl font-semibold text-gray-900">Time Series Data</h2>
            </div>
            <div className="px-4 sm:px-6 py-12 text-center text-gray-500">
              <Info className="mx-auto h-12 w-12 text-gray-400 mb-4" strokeWidth={1.5} />
              <p className="text-lg font-medium text-gray-600">Series data not yet available</p>
              <p className="text-sm text-gray-400 mt-1">The time series will be revealed once the round starts.</p>
            </div>
          </div>
        ) : (
          <div className="mb-8">
            <TimeSeriesChart
              challengeId={round.round_id}
              challengeName={round.name || `Round ${params.roundId}`}
              challengeDescription={round.description || undefined}
              registrationStart={round.registration_start || undefined}
              registrationEnd={round.registration_end || undefined}
              evaluationStart={round.end_time || undefined}
              frequency={round.frequency || undefined}
              horizon={round.horizon}
              status={round.status}
            />
          </div>
        )}

        {/* Leaderboard Section */}
        <LeaderBoardRound 
          leaderboard={leaderboard}
          loading={leaderboardLoading}
          status={round.status}
        />
      </div>
    </div>
  );
}
