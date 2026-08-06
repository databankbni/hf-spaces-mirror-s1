'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ChevronRight, Clock } from 'lucide-react';
import Pagination from './Pagination';

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

interface ModelRow {
  model_id: number;
  readable_id: string;
  model_name: string;
  seriesRanks: Record<number, { rank: number; mase: number | null }>;
  avgRank: number;
}

interface LeaderBoardRoundProps {
  leaderboard: LeaderboardEntry[];
  loading: boolean;
  status: string;
}

export default function LeaderBoardRound({ leaderboard, loading, status }: LeaderBoardRoundProps) {
  const [leaderboardPage, setLeaderboardPage] = useState(1);
  const MODELS_PER_PAGE = 10;

  // Horizontal-scroll affordance: the series matrix is wider than a phone
  // viewport, and nothing otherwise signals that it can be swiped. The hint
  // only shows while there is still something to the right.
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [showScrollHint, setShowScrollHint] = useState(false);

  useEffect(() => {
    const container = scrollRef.current;
    // The scroll container only exists once there are rows to show; the hint is
    // rendered in that same branch, so a stale value cannot become visible.
    if (loading || leaderboard.length === 0 || !container) return;

    const update = () => {
      const remaining = container.scrollWidth - container.clientWidth - container.scrollLeft;
      setShowScrollHint(remaining > 8);
    };

    update();

    const observer = new ResizeObserver(update);
    observer.observe(container);
    const table = container.firstElementChild;
    if (table) observer.observe(table);
    container.addEventListener('scroll', update, { passive: true });

    return () => {
      observer.disconnect();
      container.removeEventListener('scroll', update);
    };
  }, [loading, leaderboard, leaderboardPage]);

  return (
    <div className="mb-8 bg-white rounded-lg shadow-md overflow-hidden">
      <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
        <h2 className="text-xl font-semibold text-gray-900">
          {status === 'active' ? 'Preliminary Round Leaderboard' : 'Round Leaderboard'}
        </h2>
        <p className="text-sm text-gray-500 mt-1">
          {status === 'active' 
            ? 'Preliminary rankings while the round is still active. Final rankings for this round will be available once the round is completed.'
            : 'Model rankings per series based on MASE score'}
        </p>
      </div>
      
      {status === 'registration' ? (
        <div className="px-6 py-12 text-center text-gray-500">
          <Clock className="mx-auto h-12 w-12 text-gray-400 mb-4" strokeWidth={1.5} />
          <p className="text-lg font-medium text-gray-600">No leaderboard data available yet</p>
          <p className="text-sm text-gray-400 mt-1">The leaderboard will be available once the round begins.</p>
        </div>
      ) : loading ? (
        <div className="px-6 py-12 text-center text-gray-500">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
          Loading leaderboard...
        </div>
      ) : leaderboard.length > 0 ? (
        (() => {
          // Get unique series IDs and build a map of series_id to series_name
          const seriesIds = [...new Set(leaderboard.map(entry => entry.series_id))].sort((a, b) => a - b);
          const seriesNameMap = new Map<number, string>();
          leaderboard.forEach(entry => {
            if (!seriesNameMap.has(entry.series_id)) {
              seriesNameMap.set(entry.series_id, entry.series_name);
            }
          });
          
          // Group data by model
          const modelMap = new Map<number, ModelRow>();
          leaderboard.forEach(entry => {
            if (!modelMap.has(entry.model_id)) {
              modelMap.set(entry.model_id, {
                model_id: entry.model_id,
                readable_id: entry.readable_id,
                model_name: entry.model_name,
                seriesRanks: {},
                avgRank: 0
              });
            }
            const model = modelMap.get(entry.model_id)!;
            model.seriesRanks[entry.series_id] = { rank: entry.rank, mase: entry.mase };
          });
          
          // Calculate average rank and sort
          const modelRows = Array.from(modelMap.values()).map(model => {
            const ranks = Object.values(model.seriesRanks).map(r => r.rank);
            model.avgRank = ranks.length > 0 ? ranks.reduce((sum, r) => sum + r, 0) / ranks.length : Infinity;
            return model;
          }).sort((a, b) => a.avgRank - b.avgRank);

          // Pagination
          const totalModels = modelRows.length;
          const totalPages = Math.ceil(totalModels / MODELS_PER_PAGE);
          const startIndex = (leaderboardPage - 1) * MODELS_PER_PAGE;
          const paginatedModels = modelRows.slice(startIndex, startIndex + MODELS_PER_PAGE);

          return (
            <div>
              <div ref={scrollRef} className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th scope="col" className="px-3 py-2 sm:px-4 sm:py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider sticky left-0 bg-gray-50 z-20 border-r border-gray-200 sm:border-r-0">
                        Model
                      </th>
                      <th scope="col" className="px-2 py-2 sm:px-3 sm:py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider bg-blue-50">
                        Avg Rank
                      </th>
                      {seriesIds.map(seriesId => (
                        <th key={seriesId} scope="col" className="px-1.5 py-2 sm:px-2 sm:py-3 text-center text-xs font-medium text-gray-500 tracking-wider align-bottom min-w-[60px] max-w-[100px]">
                          <div className="text-xs leading-tight">
                            {(seriesNameMap.get(seriesId) || `Series ${seriesId}`).replace(/[_-]/g, ' ')}
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {paginatedModels.map((model) => (
                      <tr key={model.model_id} className="group hover:bg-gray-50">
                        <td className="px-3 py-2 sm:px-4 sm:py-3 whitespace-normal sm:whitespace-nowrap sticky left-0 bg-white group-hover:bg-gray-50 z-10 border-r border-gray-200 sm:border-r-0">
                          <div className="max-w-[9rem] sm:max-w-none">
                            <Link
                              href={`/models/${model.model_id}`}
                              className="text-sm font-medium text-blue-600 hover:text-blue-800"
                            >
                              {model.model_name}
                            </Link>
                            <p className="text-xs text-gray-500">{model.readable_id}</p>
                          </div>
                        </td>
                        <td className="px-2 py-2 sm:px-3 sm:py-3 text-center text-sm font-semibold text-gray-900 bg-blue-50">
                          {model.avgRank.toFixed(2)}
                        </td>
                        {seriesIds.map(seriesId => {
                          const rankData = model.seriesRanks[seriesId];
                          if (!rankData) {
                            return (
                              <td key={seriesId} className="px-2 py-2 sm:px-3 sm:py-3 text-center text-sm text-gray-400">
                                -
                              </td>
                            );
                          }
                          return (
                            <td key={seriesId} className="px-2 py-2 sm:px-3 sm:py-3 text-center">
                              <span
                                className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${
                                  rankData.rank === 1
                                    ? 'bg-yellow-100 text-yellow-800'
                                    : rankData.rank === 2
                                    ? 'bg-gray-200 text-gray-800'
                                    : rankData.rank === 3
                                    ? 'bg-orange-100 text-orange-800'
                                    : 'bg-gray-100 text-gray-600'
                                }`}
                                title={rankData.mase !== null ? `MASE: ${rankData.mase.toFixed(4)}` : 'MASE: N/A'}
                              >
                                {rankData.rank}
                              </span>
                              {/* `title` above is invisible on touch — mirror the MASE
                                  value as visible text on small screens, where the
                                  hover tooltip can never be reached. */}
                              <span className="sm:hidden mt-0.5 block text-[10px] leading-none text-gray-500">
                                {rankData.mase !== null ? rankData.mase.toFixed(3) : 'N/A'}
                              </span>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {showScrollHint && (
                <div className="sm:hidden flex items-center justify-end gap-1 px-3 py-1.5 text-xs text-gray-500 border-t border-gray-100">
                  <span>Swipe for all series</span>
                  <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} />
                </div>
              )}

              <Pagination
                currentPage={leaderboardPage}
                totalPages={totalPages}
                totalItems={totalModels}
                itemsPerPage={MODELS_PER_PAGE}
                onPageChange={setLeaderboardPage}
                itemLabel="models"
              />
            </div>
          );
        })()
      ) : (
        <div className="px-6 py-12 text-center text-gray-500">
          No leaderboard data available for this round
        </div>
      )}
    </div>
  );
}
