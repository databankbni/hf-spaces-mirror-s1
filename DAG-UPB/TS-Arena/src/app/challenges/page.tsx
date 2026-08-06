'use client';

import { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import Breadcrumbs from '@/src/components/Breadcrumbs';
import type { ChallengeDefinition } from '@/src/types/challenge';

type GroupByOption = 'none' | 'frequency' | 'horizon' | 'domain' | 'subdomain';


export default function ChallengeDefinitions() {
  const [definitions, setDefinitions] = useState<ChallengeDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<GroupByOption>('none');

  useEffect(() => {
    const fetchDefinitions = async () => {
      try {
        setLoading(true);
        const response = await fetch('/api/v1/definitions');
        
        if (!response.ok) {
          throw new Error('Failed to fetch challenges');
        }
        
        const data = await response.json();
        setDefinitions(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
        console.error('Error fetching challenges:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchDefinitions();
  }, []);

  const groupedDefinitions = useMemo(() => {
    if (groupBy === 'none') {
      return { 'All Challenges': [...definitions] };
    }

    const groups: Record<string, ChallengeDefinition[]> = {};
    
    definitions.forEach((def) => {
      let key: string;
      
      switch (groupBy) {
        case 'frequency':
          key = def.frequency || 'No Frequency';
          break;
        case 'horizon':
          key = def.horizon || 'No Horizon';
          break;
        case 'domain':
          key = def.domain || 'No Domain';
          break;
        case 'subdomain':
          key = def.subdomain || 'No Subdomain';
          break;
        default:
          key = 'Other';
      }
      
      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(def);
    });

    // Sort groups so "No X" entries appear last
    const sortedGroups: Record<string, ChallengeDefinition[]> = {};
    const sortedKeys = Object.keys(groups).sort((a, b) => {
      const aIsNo = a.startsWith('No ');
      const bIsNo = b.startsWith('No ');
      
      if (aIsNo && !bIsNo) return 1;
      if (!aIsNo && bIsNo) return -1;
      return a.localeCompare(b);
    });
    
    sortedKeys.forEach(key => {
      sortedGroups[key] = groups[key];
    });

    return sortedGroups;
  }, [definitions, groupBy]);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex justify-center items-center h-64">
          <div className="text-gray-500">Loading challenges...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded">
          <p className="font-semibold">Error loading challenges</p>
          <p className="text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <Breadcrumbs items={[{ label: 'Challenges', href: '/challenges' }]} />
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Challenges</h1>
        <p className="mt-2 text-gray-600">
          Available challenges and their configurations
        </p>
      </div>

      <div className="mb-6 flex items-center justify-end gap-3">
        <label htmlFor="groupBy" className="text-sm font-medium text-gray-700">
          Group by:
        </label>
        <select
          id="groupBy"
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as GroupByOption)}
          className="block rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-base sm:text-sm"
        >
          <option value="none">None</option>
          <option value="frequency">Frequency</option>
          <option value="horizon">Horizon</option>
          <option value="domain">Domain</option>
          <option value="subdomain">Subdomain</option>
        </select>
      </div>

      <div className="space-y-8">
        {Object.entries(groupedDefinitions).map(([groupName, groupDefs]) => (
          <div key={groupName}>
            {groupBy !== 'none' && (
              <h2 className="text-2xl font-semibold text-gray-900 mb-4">
                {groupName}
                <span className="ml-2 text-sm font-normal text-gray-500">
                  ({groupDefs.length} {groupDefs.length === 1 ? 'challenge' : 'challenges'})
                </span>
              </h2>
            )}
            
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {groupDefs.map((definition) => (
                <Link
                  key={definition.id}
                  href={`/challenges/${definition.id}`}
                  className="bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-shadow overflow-hidden flex flex-col cursor-pointer"
                >
                  <div className="p-4 sm:p-6 flex-1">
                    <div className="flex items-start justify-between mb-3">
                      <h2 className="text-xl font-semibold text-gray-900">
                        {definition.name}
                      </h2>
                    </div>

                    <p className="text-gray-600 text-sm mb-4">{definition.description}</p>

                    {definition.display_text && (
                      <p className="text-gray-700 text-sm mb-4 leading-relaxed whitespace-pre-line">
                        {definition.display_text}
                      </p>
                    )}

                    <div className="space-y-2 text-sm">

                      <div className="flex justify-between">
                        <span className="text-gray-500">Frequency:</span>
                        <span className="text-gray-900 font-medium">
                          {definition.frequency}
                        </span>
                      </div>

                      <div className="flex justify-between">
                        <span className="text-gray-500">Horizon:</span>
                        <span className="text-gray-900 font-medium">
                          {definition.horizon}
                        </span>
                      </div>

                      <div className="flex justify-between">
                        <span className="text-gray-500">Context Length:</span>
                        <span className="text-gray-900 font-medium">
                          {definition.context_length}
                        </span>
                      </div>

                      {definition.domain && (
                        <div className="flex justify-between">
                          <span className="text-gray-500">Domain:</span>
                          <span className="text-gray-900 font-medium">
                            {definition.domain}
                          </span>
                        </div>
                      )}

                      {definition.subdomain && (
                        <div className="flex justify-between">
                          <span className="text-gray-500">Subdomain:</span>
                          <span className="text-gray-900 font-medium">
                            {definition.subdomain}
                          </span>
                        </div>
                      )}

                      {(definition.next_registration_start || definition.next_registration_end) && (
                        <div className="pt-2 mt-2 border-t border-gray-200">
                          <div className="text-xs font-medium text-gray-700 mb-1">Next Registration:</div>
                          {definition.next_registration_start && (
                            <div className="text-xs text-gray-600">
                              Opens: {new Date(definition.next_registration_start).toLocaleDateString('en-US', {
                                month: 'short',
                                day: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit',
                                timeZoneName: 'short'
                              })}
                            </div>
                          )}
                          {definition.next_registration_end && (
                            <div className="text-xs text-gray-600">
                              Closes: {new Date(definition.next_registration_end).toLocaleDateString('en-US', {
                                month: 'short',
                                day: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit',
                                timeZoneName: 'short'
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="bg-gray-50 px-4 sm:px-6 py-3 border-t border-gray-200">
                    <span className="text-xs text-gray-500">ID: {definition.id}</span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>

      {definitions.length === 0 && (
        <div className="text-center py-12">
          <p className="text-gray-500">No challenges available</p>
        </div>
      )}
    </div>
  );
}
