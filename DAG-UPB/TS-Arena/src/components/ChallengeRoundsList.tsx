'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { ChevronDown, ChevronRight } from 'lucide-react';
import Pagination from '@/src/components/Pagination';
import { getDefinitionRounds } from '@/src/services/definitionService';
import type { DefinitionRound, PaginationInfo } from '@/src/types/challenge';

interface ChallengeRoundsListProps {
  definitionId: number;
  challengeId: string;
}

const ROUNDS_PER_PAGE = 10;
const STATUSES = ['active', 'registration', 'completed', 'cancelled'];

export default function ChallengeRoundsList({ definitionId, challengeId }: ChallengeRoundsListProps) {
  const [roundsData, setRoundsData] = useState<Record<string, { rounds: DefinitionRound[]; pagination: PaginationInfo | null }>>({});
  const [roundsLoading, setRoundsLoading] = useState<Record<string, boolean>>({});
  const [expandedStatuses, setExpandedStatuses] = useState<Record<string, boolean>>({
    active: true,
    registration: true,
    completed: false,
    cancelled: false,
  });

  const fetchRoundsForStatus = useCallback(async (status: string, page: number = 1) => {
    if (!definitionId) return;

    try {
      setRoundsLoading(prev => ({ ...prev, [status]: true }));
      const response = await getDefinitionRounds(definitionId, {
        page,
        pageSize: ROUNDS_PER_PAGE,
        status,
      });
      setRoundsData(prev => ({
        ...prev,
        [status]: {
          rounds: response.items,
          pagination: response.pagination,
        },
      }));
    } catch (err) {
      console.error(`Error fetching ${status} rounds:`, err);
    } finally {
      setRoundsLoading(prev => ({ ...prev, [status]: false }));
    }
  }, [definitionId]);

  // Initial fetch of rounds for all statuses
  useEffect(() => {
    if (!definitionId) return;
    
    STATUSES.forEach(status => {
      fetchRoundsForStatus(status, 1);
    });
  }, [definitionId, fetchRoundsForStatus]);

  const handlePageChange = (status: string, page: number) => {
    fetchRoundsForStatus(status, page);
  };

  const toggleStatus = (status: string) => {
    setExpandedStatuses(prev => ({
      ...prev,
      [status]: !prev[status]
    }));
  };

  const getStatusConfig = (status: string) => {
    const configs: Record<string, { label: string; color: string; bgColor: string; borderColor: string }> = {
      registration: {
        label: 'Registration',
        color: 'text-yellow-800',
        bgColor: 'bg-yellow-50',
        borderColor: 'border-yellow-200'
      },
      active: {
        label: 'Active',
        color: 'text-green-800',
        bgColor: 'bg-green-50',
        borderColor: 'border-green-200'
      },
      completed: {
        label: 'Completed',
        color: 'text-blue-800',
        bgColor: 'bg-blue-50',
        borderColor: 'border-blue-200'
      },
      cancelled: {
        label: 'Cancelled',
        color: 'text-gray-800',
        bgColor: 'bg-gray-50',
        borderColor: 'border-gray-200'
      }
    };
    return configs[status] || {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      color: 'text-gray-800',
      bgColor: 'bg-gray-50',
      borderColor: 'border-gray-200'
    };
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
      <div className="px-4 sm:px-6 py-5 border-b border-gray-200 bg-gray-50">
        <h2 className="text-xl font-bold text-gray-900">Challenge Rounds</h2>
        <p className="mt-1 text-sm text-gray-500">
          All rounds associated with this challenge, grouped by status
        </p>
      </div>

      <div className="divide-y divide-gray-200">
        {STATUSES.map((status) => {
          const statusData = roundsData[status];
          const config = getStatusConfig(status);
          const isExpanded = expandedStatuses[status];
          const isLoading = roundsLoading[status];
          const rounds = statusData?.rounds || [];
          const pagination = statusData?.pagination;
          const totalRounds = pagination?.total_items || 0;
          const currentPage = pagination?.page || 1;
          const totalPages = pagination?.total_pages || 1;

          return (
            <div key={status} className="border-b border-gray-200 last:border-b-0">
              {/* Status Header */}
              <button
                onClick={() => toggleStatus(status)}
                className={`w-full px-6 py-4 flex items-center justify-between hover:bg-gray-50 transition-colors ${config.bgColor}`}
              >
                <div className="flex items-center space-x-3">
                  {isExpanded ? (
                    <ChevronDown className="h-5 w-5 text-gray-500" />
                  ) : (
                    <ChevronRight className="h-5 w-5 text-gray-500" />
                  )}
                  <span className={`text-lg font-semibold ${config.color}`}>
                    {config.label}
                  </span>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    status === 'active' 
                      ? 'bg-green-100 text-green-800'
                      : status === 'registration'
                      ? 'bg-yellow-100 text-yellow-800'
                      : status === 'completed'
                      ? 'bg-blue-100 text-blue-800'
                      : status === 'cancelled'
                      ? 'bg-gray-100 text-gray-800'
                      : 'bg-gray-100 text-gray-800'
                  }`}>
                    {totalRounds} {totalRounds === 1 ? 'round' : 'rounds'}
                  </span>
                </div>
              </button>

              {/* Expandable Content */}
              {isExpanded && (
                <div className="overflow-x-auto">
                  {isLoading ? (
                    <div className="px-4 sm:px-6 py-8 flex items-center justify-center">
                      <div className="flex items-center gap-3 text-gray-500">
                        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
                        <span>Loading rounds...</span>
                      </div>
                    </div>
                  ) : totalRounds === 0 ? (
                    <div className="px-4 sm:px-6 py-8 text-center text-gray-500">
                      No rounds available for this status
                    </div>
                  ) : (
                    <>
                      <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                          <tr>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Name
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Description
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Registration
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Start Time
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              End Time
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Context Length
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Frequency
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Horizon
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Domains
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Categories
                            </th>
                            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                              Subcategories
                            </th>
                          </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                          {rounds.map((round, roundIndex) => {
                            return (
                              <tr key={`round-${round.id}-${roundIndex}`} className="hover:bg-gray-50">
                                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                  <Link 
                                    href={`/challenges/${challengeId}/${round.id}`}
                                    className="text-blue-600 hover:text-blue-800 hover:underline"
                                  >
                                    {round.name}
                                  </Link>
                                </td>
                                <td className="px-6 py-4 text-sm text-gray-900 max-w-xs">
                                  {round.description}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                  <div>{new Date(round.registration_start).toLocaleDateString('en-US', {
                                    year: 'numeric',
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                    timeZoneName: 'short',
                                  })}</div>
                                  <div className="text-xs text-gray-500">to</div>
                                  <div>{new Date(round.registration_end).toLocaleDateString('en-US', {
                                    year: 'numeric',
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                    timeZoneName: 'short',
                                  })}</div>
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                  {new Date(round.start_time).toLocaleDateString('en-US', {
                                    year: 'numeric',
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                    timeZoneName: 'short',
                                  })}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                  {new Date(round.end_time).toLocaleDateString('en-US', {
                                    year: 'numeric',
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                    timeZoneName: 'short',
                                  })}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                  {round.context_length}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                  {round.frequency}
                                </td>
                                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                  {round.horizon}
                                </td>
                                <td className="px-6 py-4 text-sm text-gray-900">
                                  <div className="flex flex-wrap gap-1">
                                    {round.domains && round.domains.length > 0 ? (
                                      round.domains.map((domain, idx) => (
                                        <span key={idx} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800">
                                          {domain}
                                        </span>
                                      ))
                                    ) : (
                                      <span className="text-gray-400 text-xs">-</span>
                                    )}
                                  </div>
                                </td>
                                <td className="px-6 py-4 text-sm text-gray-900">
                                  <div className="flex flex-wrap gap-1">
                                    {round.categories && round.categories.length > 0 ? (
                                      round.categories.map((category, idx) => (
                                        <span key={idx} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-800">
                                          {category}
                                        </span>
                                      ))
                                    ) : (
                                      <span className="text-gray-400 text-xs">-</span>
                                    )}
                                  </div>
                                </td>
                                <td className="px-6 py-4 text-sm text-gray-900">
                                  <div className="flex flex-wrap gap-1">
                                    {round.subcategories && round.subcategories.length > 0 ? (
                                      round.subcategories.map((subcategory, idx) => (
                                        <span key={idx} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-pink-100 text-pink-800">
                                          {subcategory}
                                        </span>
                                      ))
                                    ) : (
                                      <span className="text-gray-400 text-xs">-</span>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>

                      <Pagination
                        currentPage={currentPage}
                        totalPages={totalPages}
                        totalItems={totalRounds}
                        itemsPerPage={ROUNDS_PER_PAGE}
                        onPageChange={(page) => handlePageChange(status, page)}
                        itemLabel="rounds"
                      />
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
