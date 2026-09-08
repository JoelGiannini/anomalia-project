import 'package:flutter/material.dart';
import '../services/api_service.dart';
import 'login_screen.dart';

class WelcomeRoleScreen extends StatefulWidget {
  const WelcomeRoleScreen({super.key});

  @override
  State<WelcomeRoleScreen> createState() => _WelcomeRoleScreenState();
}

class _WelcomeRoleScreenState extends State<WelcomeRoleScreen> {
  String _selectedRole = 'operador_sre'; // Rol por defecto
  bool _isLoading = false;
  String _message = '';

  final List<Map<String, String>> _availableRoles = [
    {'id': 'operador_sre', 'name': 'Operador SRE (Monitoreo y Alertas)'},
    {'id': 'devops_engineer', 'name': 'Ingeniero DevOps (Despliegues y Configs)'},
    {'id': 'auditor', 'name': 'Auditor / Seguridad'},
  ];

  void _submitRoleRequest() async {
    setState(() {
      _isLoading = true;
      _message = '';
    });

    try {
      // Llamada al endpoint que enviamos arriba
      await ApiService.requestRole(_selectedRole);
      
      setState(() {
        _message = '¡Solicitud enviada con éxito! Un administrador debe aprobar tu acceso.';
      });
    } catch (e) {
      setState(() {
        _message = 'Error al enviar la solicitud: ${e.toString().replaceAll("Exception: ", "")}';
      });
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Bienvenido a anomalIAGW'),
        automaticallyImplyLeading: false,
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () {
              Navigator.pushReplacement(
                context,
                MaterialPageRoute(builder: (context) => const LoginScreen()),
              );
            },
          )
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24.0),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 450),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(Icons.verified_user_outlined, size: 64, color: Colors.blue),
                const SizedBox(height: 16),
                const Text(
                  'Autenticación OIDC Exitosa',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 8),
                const Text(
                  'Tu cuenta externa fue reconocida, pero aún no tenés un rol asignado en el sistema. Seleccioná el perfil que necesitás para que un administrador lo apruebe:',
                  style: TextStyle(fontSize: 14, color: Colors.grey),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 32),
                DropdownButtonFormField<String>(
                  value: _selectedRole,
                  decoration: const InputDecoration(
                    labelText: 'Rol / Perfil Solicitado',
                    border: OutlineInputBorder(),
                  ),
                  items: _availableRoles.map((role) {
                    return DropdownMenuItem(
                      value: role['id'],
                      child: Text(role['name']!),
                    );
                  }).toList(),
                  onChanged: (value) {
                    setState(() {
                      _selectedRole = value!;
                    });
                  },
                ),
                const SizedBox(height: 24),
                if (_message.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16.0),
                    child: Text(
                      _message,
                      style: TextStyle(
                        color: _message.contains('éxito') ? Colors.green : Colors.red,
                        fontWeight: FontWeight.w500,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ),
                _isLoading
                    ? const Center(child: CircularProgressIndicator())
                    : ElevatedButton(
                        onPressed: _submitRoleRequest,
                        style: ElevatedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 14),
                        ),
                        child: const Text('Solicitar Rol a Administrador', style: TextStyle(fontSize: 16)),
                      ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
