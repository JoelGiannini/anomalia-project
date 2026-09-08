import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';
import 'user_dashboard_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  
  bool _isLoading = false;
  bool _isLoadingConfig = true;
  String _errorMessage = '';
  String _authMode = 'hybrid'; // por defecto

  @override
  void initState() {
    super.initState();
    _loadAuthConfig();
  }

  Future<void> _loadAuthConfig() async {
    try {
      final settings = await ApiService.getAuthSettings();
      setState(() {
        _authMode = settings['auth_mode'] ?? 'hybrid';
        _isLoadingConfig = false;
      });
    } catch (e) {
      setState(() {
        _authMode = 'hybrid';
        _isLoadingConfig = false;
      });
    }
  }

  void _login() async {
    final username = _usernameController.text.trim();
    final password = _passwordController.text.trim();

    if (username.isEmpty || password.isEmpty) {
      setState(() {
        _errorMessage = 'Por favor, complete todos los campos.';
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = '';
    });

    try {
      final response = await ApiService.login(username, password);
      
      if (!mounted) return;
      
      final role = response['role'] ?? 'user';
      final usernameResponse = response['username'] ?? username;

      // Guardar el rol y el usuario en SharedPreferences para controlarlos en el panel
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('user_role', role);
      await prefs.setString('username', usernameResponse);

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('¡Bienvenido, $usernameResponse ($role)!')),
      );

      // Redirigir siempre al Panel de Usuario por defecto
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) => const UserDashboardScreen(),
        ),
      );
      
    } catch (e) {
      String cleanError = e.toString().replaceAll("Exception: ", "");
      if (cleanError.contains('404') || cleanError.contains('Not Found')) {
        cleanError = 'No se pudo conectar con el servidor. Verificá la URL de la API.';
      }

      setState(() {
        _errorMessage = cleanError;
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  void _loginWithOidc() async {
    try {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Obteniendo enlace de redirección OIDC...')),
      );

      // Llama al servicio para obtener la URL del IdP Keycloak / Proveedor
      final authUrl = await ApiService.getOidcLoginUrl();
      final uri = Uri.parse(authUrl);

      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } else {
        throw Exception('No se pudo abrir la URL del Proveedor de Identidad');
      }
    } catch (e) {
      if (!mounted) return;
      String cleanError = e.toString().replaceAll("Exception: ", "");
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error OIDC: $cleanError'), backgroundColor: Colors.red),
      );
    }
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('anomalIAGW - Acceso al Sistema')),
      body: _isLoadingConfig
          ? const Center(child: CircularProgressIndicator())
          : Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24.0),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 400),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        'Autenticación',
                        style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _authMode == 'oidc_only'
                            ? 'Modo exclusivo OIDC'
                            : _authMode == 'hybrid'
                                ? 'Modo Híbrido (Local y OIDC)'
                                : 'Acceso por Usuario Local',
                        style: const TextStyle(fontSize: 14, color: Colors.grey),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 24),

                      // Formulario Local (Visible si no es oidc_only)
                      if (_authMode != 'oidc_only') ...[
                        TextField(
                          controller: _usernameController,
                          decoration: const InputDecoration(
                            labelText: 'Usuario',
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _passwordController,
                          obscureText: true,
                          decoration: const InputDecoration(
                            labelText: 'Contraseña',
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 20),
                        if (_errorMessage.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 16.0),
                            child: Text(
                              _errorMessage,
                              style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w500),
                              textAlign: TextAlign.center,
                            ),
                          ),
                        _isLoading
                            ? const Center(child: CircularProgressIndicator())
                            : ElevatedButton(
                                onPressed: _login,
                                style: ElevatedButton.styleFrom(
                                  padding: const EdgeInsets.symmetric(vertical: 14),
                                ),
                                child: const Text('Ingresar con Credenciales', style: TextStyle(fontSize: 16)),
                              ),
                      ],

                      // Botón OIDC (Visible si es hybrid o oidc_only)
                      if (_authMode == 'hybrid' || _authMode == 'oidc_only') ...[
                        if (_authMode == 'hybrid') ...[
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 20.0),
                            child: Divider(),
                          ),
                        ],
                        OutlinedButton.icon(
                          onPressed: _loginWithOidc,
                          icon: const Icon(Icons.security),
                          style: OutlinedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(vertical: 14),
                          ),
                          label: const Text('Iniciar sesión con OIDC (Externo)', style: TextStyle(fontSize: 16)),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
    );
  }
}
