module ApplicationHelper
  def format_temp(value)
    return "--" if value.blank?
    "#{value.round}°#{unit_system == 'imperial' ? 'F' : 'C'}"
  end

  def format_wind(value)
    return "--" if value.blank?
    "#{value.round} #{unit_system == 'imperial' ? 'mph' : 'km/h'}"
  end

  def format_precip(value)
    return "--" if value.blank?
    "#{value} #{unit_system == 'imperial' ? 'in' : 'mm'}"
  end

  def metric_temp(value)
    return 0.0 if value.blank?
    unit_system == 'imperial' ? ((value.to_f - 32) * 5.0 / 9.0).round(1) : value.to_f
  end

  def metric_wind(value)
    return 0.0 if value.blank?
    unit_system == 'imperial' ? (value.to_f / 0.621371).round(1) : value.to_f
  end

  def metric_precip(value)
    return 0.0 if value.blank?
    unit_system == 'imperial' ? (value.to_f * 25.4).round(2) : value.to_f
  end
end
