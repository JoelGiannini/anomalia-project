import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  static const String baseUrl = "http://127.0.0.1:8000/api/v1";

  static Future<Map<String, String>> _authHeaders() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString('auth_token');
    return {
      "Content-Type": "application/json",
      if (token != null) "Authorization": "Bearer $token",
    };
  }

  static Future<Map<String, dynamic>> getAuthSettings() async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/settings/auth'),
        headers: {"Content-Type": "application/json"},
      );

      if (response.statusCode == 200) {
        return jsonDecode(response.body);
      } else {
        return {"auth_mode": "hybrid"};
      }
    } catch (e) {
      return {"auth_mode": "hybrid"};
    }
  }

  static Future<String> getOidcLoginUrl() async {
    try {
      final response = await http.get(
        Uri.parse('$baseUrl/oidc/login'),
        headers: {"Content-Type": "application/json"},
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        return data['auth_url'] ?? data['url'] ?? '';
      } else {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al obtener la URL de OIDC');
      }
    } catch (e) {
      throw Exception('No se pudo conectar con el servidor para OIDC');
    }
  }

  /// Método agregado para almacenar credenciales devueltas por OIDC en SharedPreferences
  static Future<void> saveOidcTokens(String accessToken, String refreshToken, {String username = 'Usuario OIDC', String role = 'user'}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', accessToken);
    await prefs.setString('refresh_token', refreshToken);
    await prefs.setString('user_role', role);
    await prefs.setString('username', username);
  }

  static Future<Map<String, dynamic>> login(String username, String password) async {
    final response = await http.post(
      Uri.parse('$baseUrl/auth/login'),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"username": username, "password": password}),
    );

    if (response.statusCode == 200) {
      try {
        final data = jsonDecode(response.body);
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('auth_token', data['access_token']);
        await prefs.setString('user_role', data['role']);
        await prefs.setString('username', data['username']);
        return data;
      } catch (e) {
        throw Exception('Error al procesar la respuesta del servidor.');
      }
    } else {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error de autenticación');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> requestRole(String role) async {
    final headers = await _authHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/auth/request-role'),
      headers: headers,
      body: jsonEncode({"requested_role": role}),
    );

    if (response.statusCode != 200) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al solicitar el rol');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  // ==========================================
  // MÉTODOS ABM: USUARIOS
  // ==========================================

  static Future<List<dynamic>> getUsers() async {
    final headers = await _authHeaders();
    final response = await http.get(
      Uri.parse('$baseUrl/admin/users'),
      headers: headers,
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['users'] ?? [];
    } else {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al cargar usuarios');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> createUser(Map<String, dynamic> userData) async {
    final headers = await _authHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/admin/users'),
      headers: headers,
      body: jsonEncode(userData),
    );

    if (response.statusCode != 200 && response.statusCode != 201) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al crear usuario');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> updateUser(String userId, Map<String, dynamic> userData) async {
    final headers = await _authHeaders();
    final response = await http.put(
      Uri.parse('$baseUrl/admin/users/$userId'),
      headers: headers,
      body: jsonEncode(userData),
    );

    if (response.statusCode != 200) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al actualizar usuario');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> deleteUser(String userId) async {
    final headers = await _authHeaders();
    final response = await http.delete(
      Uri.parse('$baseUrl/admin/users/$userId'),
      headers: headers,
    );

    if (response.statusCode != 200 && response.statusCode != 204) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al eliminar usuario');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  // ==========================================
  // MÉTODOS ABM: ROLES
  // ==========================================

  static Future<List<dynamic>> getRoles() async {
    final headers = await _authHeaders();
    final response = await http.get(
      Uri.parse('$baseUrl/roles'),
      headers: headers,
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data is List ? data : (data['roles'] ?? []);
    } else {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al cargar roles');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> createRole(Map<String, dynamic> roleData) async {
    final headers = await _authHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/roles'),
      headers: headers,
      body: jsonEncode(roleData),
    );

    if (response.statusCode != 200 && response.statusCode != 201) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al crear rol');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> updateRole(String roleId, Map<String, dynamic> roleData) async {
    final headers = await _authHeaders();
    final response = await http.put(
      Uri.parse('$baseUrl/roles/$roleId'),
      headers: headers,
      body: jsonEncode(roleData),
    );

    if (response.statusCode != 200) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al actualizar rol');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> deleteRole(String roleId) async {
    final headers = await _authHeaders();
    final response = await http.delete(
      Uri.parse('$baseUrl/roles/$roleId'),
      headers: headers,
    );

    if (response.statusCode != 200 && response.statusCode != 204) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al eliminar rol');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  // ==========================================
  // MÉTODOS ABM: PERFILES
  // ==========================================

  static Future<List<dynamic>> getProfiles() async {
    final headers = await _authHeaders();
    final response = await http.get(
      Uri.parse('$baseUrl/profiles'),
      headers: headers,
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data is List ? data : (data['profiles'] ?? []);
    } else {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al cargar perfiles');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> createProfile(Map<String, dynamic> profileData) async {
    final headers = await _authHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/profiles'),
      headers: headers,
      body: jsonEncode(profileData),
    );

    if (response.statusCode != 200 && response.statusCode != 201) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al crear perfil');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> updateProfile(String profileId, Map<String, dynamic> profileData) async {
    final headers = await _authHeaders();
    final response = await http.put(
      Uri.parse('$baseUrl/profiles/$profileId'),
      headers: headers,
      body: jsonEncode(profileData),
    );

    if (response.statusCode != 200) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al actualizar perfil');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> deleteProfile(String profileId) async {
    final headers = await _authHeaders();
    final response = await http.delete(
      Uri.parse('$baseUrl/profiles/$profileId'),
      headers: headers,
    );

    if (response.statusCode != 200 && response.statusCode != 204) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al eliminar perfil');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  // ==========================================
  // MÉTODOS OIDC PROVIDERS
  // ==========================================

  static Future<List<dynamic>> getOidcProviders() async {
    final headers = await _authHeaders();
    final response = await http.get(
      Uri.parse('$baseUrl/oidc/providers'),
      headers: headers,
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data is List ? data : (data['providers'] ?? []);
    } else {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al cargar proveedores OIDC');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> createOidcProvider(Map<String, dynamic> providerData) async {
    final headers = await _authHeaders();
    final response = await http.post(
      Uri.parse('$baseUrl/oidc/providers'),
      headers: headers,
      body: jsonEncode(providerData),
    );

    if (response.statusCode != 200 && response.statusCode != 201) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al crear proveedor OIDC');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> updateOidcProvider(dynamic providerId, Map<String, dynamic> providerData) async {
    final headers = await _authHeaders();
    final id = providerId is int ? providerId : int.parse(providerId.toString());
    final response = await http.put(
      Uri.parse('$baseUrl/oidc/providers/$id'),
      headers: headers,
      body: jsonEncode(providerData),
    );

    if (response.statusCode != 200) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al actualizar proveedor OIDC');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }

  static Future<void> deleteOidcProvider(dynamic providerId) async {
    final headers = await _authHeaders();
    final id = providerId is int ? providerId : int.parse(providerId.toString());
    final response = await http.delete(
      Uri.parse('$baseUrl/oidc/providers/$id'),
      headers: headers,
    );

    if (response.statusCode != 200 && response.statusCode != 204) {
      try {
        final errorData = jsonDecode(response.body);
        throw Exception(errorData['detail'] ?? 'Error al eliminar proveedor OIDC');
      } catch (_) {
        throw Exception('Error del servidor (${response.statusCode})');
      }
    }
  }
}
