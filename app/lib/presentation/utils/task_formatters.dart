import 'package:url_launcher/url_launcher.dart';

const _weekdaysShort = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const _weekdaysLong = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];
const _monthsShort = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];
const _monthsLong = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

String _formatTime12h(DateTime dt) {
  final hour24 = dt.hour;
  final period = hour24 >= 12 ? 'PM' : 'AM';
  final hour12 = hour24 % 12 == 0 ? 12 : hour24 % 12;
  final minute = dt.minute.toString().padLeft(2, '0');
  return '$hour12:$minute $period';
}

/// Formats a meeting timestamp like `Tue, Nov 25, 2026 • 10:00 AM`.
String formatTaskDateTimeShort(DateTime? dt) {
  if (dt == null) return 'Time not specified';
  final weekday = _weekdaysShort[dt.weekday - 1];
  final month = _monthsShort[dt.month - 1];
  return '$weekday, $month ${dt.day}, ${dt.year} • ${_formatTime12h(dt)}';
}

/// Formats a full date header like `Tuesday, November 25, 2026`.
String formatTaskDateLong(DateTime? dt) {
  if (dt == null) return 'Date not specified';
  final weekday = _weekdaysLong[dt.weekday - 1];
  final month = _monthsLong[dt.month - 1];
  return '$weekday, $month ${dt.day}, ${dt.year}';
}

/// Formats a time range like `10:00 AM – 10:30 AM` or single start time.
String formatTaskTimeRange(DateTime? start, DateTime? end) {
  if (start == null) return 'Time not specified';
  if (end == null) return _formatTime12h(start);
  return '${_formatTime12h(start)} – ${_formatTime12h(end)}';
}

/// Extracts a concise host + path display label for a meeting link.
String formatShortLinkLabel(String rawUrl) {
  final uri = Uri.tryParse(rawUrl);
  if (uri == null || uri.host.isEmpty) return rawUrl;
  final path = uri.path == '/' ? '' : uri.path;
  final compact = '${uri.host}$path';
  return compact.length > 42 ? '${compact.substring(0, 39)}...' : compact;
}

/// Safely opens only external HTTPS meeting/calendar URLs in the user's browser.
Future<bool> launchSafeMeetingUrl(String rawUrl) async {
  final uri = Uri.tryParse(rawUrl.trim());
  if (uri == null || uri.scheme.toLowerCase() != 'https' || uri.host.isEmpty) {
    return false;
  }
  return launchUrl(uri, mode: LaunchMode.externalApplication);
}
