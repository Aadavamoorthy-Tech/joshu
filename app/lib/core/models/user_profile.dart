/// User profile from FastAPI /oauth/token endpoint.
class UserProfile {
  final String googleId;
  final String email;
  final String name;
  final String? pictureUrl;

  const UserProfile({
    required this.googleId,
    required this.email,
    required this.name,
    this.pictureUrl,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) => UserProfile(
    googleId: json['google_id'] as String,
    email: json['email'] as String,
    name: json['name'] as String,
    pictureUrl: json['picture_url'] as String?,
  );

  Map<String, dynamic> toJson() => {
    'google_id': googleId,
    'email': email,
    'name': name,
    'picture_url': pictureUrl,
  };
}
