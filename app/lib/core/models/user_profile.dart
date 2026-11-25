/// Authenticated user profile returned by FastAPI `/auth/callback`, `/auth/refresh`, or `/auth/me`.
class UserProfile {
  final String? googleId;
  final String email;
  final String name;
  final String? pictureUrl;

  const UserProfile({
    this.googleId,
    required this.email,
    required this.name,
    this.pictureUrl,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
        googleId: json['google_id'] as String?,
        email: json['email'] as String? ?? '',
        name: json['name'] as String? ?? (json['email'] as String? ?? 'User'),
        pictureUrl: json['picture_url'] as String?,
      );

  Map<String, dynamic> toJson() => {
        if (googleId != null) 'google_id': googleId,
        'email': email,
        'name': name,
        'picture_url': pictureUrl,
      };
}
