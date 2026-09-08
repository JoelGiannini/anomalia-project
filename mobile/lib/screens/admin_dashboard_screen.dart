import 'package:flutter/material.dart';
import 'abm_screen.dart';
import 'oidc_abm_screen.dart'; // <-- Nueva pantalla que crearemos

class AdminDashboardScreen extends StatelessWidget {
  const AdminDashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.colorScheme.surfaceContainerLowest,
      appBar: AppBar(
        title: const Text(
          'Panel de Administración',
          style: TextStyle(fontWeight: FontWeight.bold, fontSize: 20),
        ),
        elevation: 0,
        centerTitle: true,
        actions: [
          IconButton(
            icon: const Icon(Icons.logout_rounded),
            tooltip: 'Cerrar Sesión',
            onPressed: () {
              Navigator.pop(context);
            },
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Tarjeta de Bienvenida / Estado del Sistema
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(20.0),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [theme.colorScheme.primary, theme.colorScheme.tertiary],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(16),
                boxShadow: [
                  BoxShadow(
                    color: theme.colorScheme.primary.withOpacity(0.3),
                    blurRadius: 10,
                    offset: const Offset(0, 4),
                  ),
                ],
              ),
              child: const Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'anomalIAGW Core',
                    style: TextStyle(
                      color: Colors.white70,
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                  SizedBox(height: 8),
                  Text(
                    'Modo Administrador Activo',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 22,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  SizedBox(height: 4),
                  Text(
                    'Sistema operando con normalidad y pasarela sincronizada.',
                    style: TextStyle(color: Colors.white70, fontSize: 13),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),

            // Título de sección
            const Text(
              'Configuración y Gestión',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                letterSpacing: 0.5,
              ),
            ),
            const SizedBox(height: 12),

            // Opciones del Dashboard en Tarjetas Modernas
            _AdminMenuCard(
              icon: Icons.security_rounded,
              iconColor: Colors.indigo,
              title: 'Configuración de IdP (OIDC)',
              subtitle: 'Gestionar proveedores de identidad y tokens',
              onTap: () {
                // Navegar a la pantalla de OIDC
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => const OidcAbmScreen()),
                );
              },
            ),
            const SizedBox(height: 12),
            _AdminMenuCard(
              icon: Icons.psychology_rounded,
              iconColor: Colors.deepPurple,
              title: 'Proveedor de IA',
              subtitle: 'Modelos, umbrales y parámetros de inferencia',
              onTap: () {
                // TODO: Navegar a pantalla de IA
              },
            ),
            const SizedBox(height: 12),
            _AdminMenuCard(
              icon: Icons.group_rounded,
              iconColor: Colors.teal,
              title: 'Gestión ABM',
              subtitle: 'Administración de usuarios, altas y roles',
              onTap: () {
                // Navegación hacia la pantalla ABM
                Navigator.push(
                  context,
                  MaterialPageRoute(builder: (context) => const AbmScreen()),
                );
              },
            ),
            const SizedBox(height: 12),
            _AdminMenuCard(
              icon: Icons.notifications_active_rounded,
              iconColor: Colors.amber,
              title: 'Alertas y Notificaciones',
              subtitle: 'Historial y gestión de push notifications',
              onTap: () {
                // TODO: Navegar a panel de alertas
              },
            ),
          ],
        ),
      ),
    );
  }
}

// Widget auxiliar privado para mantener el código limpio y profesional
class _AdminMenuCard extends StatelessWidget {
  final IconData icon;
  final Color iconColor;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _AdminMenuCard({
    required this.icon,
    required this.iconColor,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16.0),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: iconColor.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(icon, color: iconColor, size: 26),
              ),
              const SizedBox(height: 0, width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      subtitle,
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.grey[600],
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward_ios_rounded, size: 16, color: Colors.grey),
            ],
          ),
        ),
      ),
    );
  }
}
