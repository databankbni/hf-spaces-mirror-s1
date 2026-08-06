import React from 'react';

export interface DetailField {
  label: string;
  value: string | number | React.ReactNode;
  mono?: boolean;
}

interface DetailsCardProps {
  title: string;
  id: string;
  description?: string;
  displayText?: string | null;
  fields: DetailField[];
  registrationPeriod?: {
    start?: string;
    end?: string;
  };
}

export default function DetailsCard({
  title,
  id,
  description,
  displayText,
  fields,
  registrationPeriod
}: DetailsCardProps) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 sm:px-6 py-6 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
        <h1 className="text-3xl font-bold text-gray-900">{title}</h1>
        <p className="mt-2 text-sm font-medium text-gray-500">{id}</p>
      </div>

      {/* Description */}
      {description && (
        <div className="px-4 sm:px-6 py-5 border-b border-gray-200 bg-gray-50">
          <p className="text-gray-700 leading-relaxed">{description}</p>
        </div>
      )}

      {/* Long-form description (display_text) */}
      {displayText && (
        <div className="px-4 sm:px-6 py-5 border-b border-gray-200">
          <p className="text-gray-700 leading-relaxed whitespace-pre-line">{displayText}</p>
        </div>
      )}

      {/* Main Content */}
      <div className="px-4 sm:px-6 py-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {fields.map((field, index) => (
            <div key={index} className="space-y-1">
              <dt className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                {field.label}
              </dt>
              <dd className={`text-base font-medium text-gray-900 ${field.mono ? 'font-mono bg-gray-50 px-3 py-2 rounded border border-gray-200 break-all' : ''}`}>
                {field.value}
              </dd>
            </div>
          ))}
        </div>

        {/* Registration Period */}
        {registrationPeriod && (registrationPeriod.start || registrationPeriod.end) && (
          <div className="mt-8 pt-6 border-t border-gray-200">
            <h3 className="text-sm font-semibold text-gray-900 mb-4 uppercase tracking-wider">
              Next Registration Period
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {registrationPeriod.start && (
                <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3">
                  <div className="text-xs font-semibold text-green-700 uppercase tracking-wider mb-1">
                    Opens
                  </div>
                  <div className="text-sm font-medium text-green-900">
                    {new Date(registrationPeriod.start).toLocaleDateString('en-US', {
                      weekday: 'short',
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                      timeZoneName: 'short'
                    })}
                  </div>
                </div>
              )}
              {registrationPeriod.end && (
                <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                  <div className="text-xs font-semibold text-red-700 uppercase tracking-wider mb-1">
                    Closes
                  </div>
                  <div className="text-sm font-medium text-red-900">
                    {new Date(registrationPeriod.end).toLocaleDateString('en-US', {
                      weekday: 'short',
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                      timeZoneName: 'short'
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
