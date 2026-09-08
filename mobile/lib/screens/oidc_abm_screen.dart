import 'package:flutter/material.dart';
import '../services/api_service.dart';

class OidcAbmScreen extends StatefulWidget {
  const OidcAbmScreen({super.key});

  @override
  State<OidcAbmScreen> createState() => _OidcAbmScreenState();
}

class _OidcAbmScreenState extends State<OidcAbmScreen> {
  late Future<List<dynamic>> _providersFuture;

  @override
  void initState() {
    super.initState();
    _loadProviders();
  }

  void _loadProviders() {
    setState(() {
      _providersFuture = ApiService.getOidcProviders();
    });
  }

  void _showProviderDialog({Map<String, dynamic>? provider}) {
    final isEditing = provider != null;
    final nameController = TextEditingController(text: provider?['name'] ?? '');
    final issuerController = TextEditingController(text: provider?['issuer_url'] ?? '');
    final clientIdController = TextEditingController(text: provider?['client_id'] ?? '');
    final clientSecretController = TextEditingController(text: provider?['client_secret'] ?? '');

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(isEditing ? 'Editar Proveedor OIDC' : 'Nuevo Proveedor OIDC'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameController,
                decoration: const InputDecoration(labelText: 'Nombre del Proveedor (ej. Keycloak, Auth0)'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: issuerController,
                decoration: const InputDecoration(labelText: 'URL del Emisor (Issuer URL)'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: clientIdController,
                decoration: const InputDecoration(labelText: 'Client ID'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: clientSecretController,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Client Secret'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar'),
          ),
          ElevatedButton(
            onPressed: () async {
              final data = {
                'name': nameController.text.trim(),
                'issuer_url': issuerController.text.trim(),
                'client_id': clientIdController.text.trim(),
                'client_secret': clientSecretController.text.trim(),
              };

              try {
                if (isEditing) {
                  final providerId = provider['id'].toString();
                  await ApiService.updateOidcProvider(providerId, data);
                } else {
                  await ApiService.createOidcProvider(data);
                }

                if (mounted) {
                  Navigator.pop(context);
                  _loadProviders();
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(isEditing ? 'Proveedor actualizado con éxito' : 'Proveedor creado con éxito')),
                  );
                }
              } catch (e) {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Error: ${e.toString().replaceAll("Exception: ", "")}'), backgroundColor: Colors.red),
                  );
                }
              }
            },
            child: Text(isEditing ? 'Guardar' : 'Crear'),
          ),
        ],
      ),
    );
  }

  void _confirmDelete(String providerId, String providerName) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Eliminar Proveedor'),
        content: Text('¿Estás seguro de que deseas eliminar el proveedor "$providerName"?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar'),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red, foregroundColor: Colors.white),
            onPressed: () async {
              try {
                await ApiService.deleteOidcProvider(providerId);
                if (mounted) {
                  Navigator.pop(context);
                  _loadProviders();
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Proveedor eliminado correctamente')),
                  );
                }
              } catch (e) {
                if (mounted) {
                  Navigator.pop(context);
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Error al eliminar: ${e.toString().replaceAll("Exception: ", "")}'), backgroundColor: Colors.red),
                  );
                }
              }
            },
            child: const Text('Eliminar'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Gestión de Proveedores OIDC'),
        centerTitle: true,
      ),
      body: FutureBuilder<List<dynamic>>(
        future: _providersFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          } else if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(20.0),
                child: Text(
                  'Error al cargar proveedores:\n${snapshot.error.toString().replaceAll("Exception: ", "")}',
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.red),
                ),
              ),
            );
          } else if (!snapshot.hasData || snapshot.data!.isEmpty) {
            return const Center(
              child: Text(
                'No hay proveedores OIDC configurados.',
                style: TextStyle(fontSize: 16, color: Colors.grey),
              ),
            );
          }

          final providers = snapshot.data!;
          return ListView.builder(
            padding: const EdgeInsets.all(16.0),
            itemCount: providers.length,
            itemBuilder: (context, index) {
              final provider = providers[index];
              final name = provider['name'] ?? 'Sin nombre';
              final issuer = provider['issuer_url'] ?? 'Sin emisor';
              final clientId = provider['client_id'] ?? 'Sin client_id';
              final id = provider['id']?.toString() ?? '';

              return Card(
                elevation: 2,
                margin: const EdgeInsets.only(bottom: 12),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                child: ListTile(
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  leading: CircleAvatar(
                    backgroundColor: Colors.indigo.withOpacity(0.1),
                    child: const Icon(Icons.security, color: Colors.indigo),
                  ),
                  title: Text(name, style: const TextStyle(fontWeight: FontWeight.bold)),
                  subtitle: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const SizedBox(height: 4),
                      Text('Emisor: $issuer', style: const TextStyle(fontSize: 12)),
                      Text('Client ID: $clientId', style: const TextStyle(fontSize: 12, color: Colors.grey)),
                    ],
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        icon: const Icon(Icons.edit_rounded, color: Colors.blue),
                        onPressed: () => _showProviderDialog(provider: provider),
                      ),
                      IconButton(
                        icon: const Icon(Icons.delete_rounded, color: Colors.red),
                        onPressed: () => _confirmDelete(id, name),
                      ),
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _showProviderDialog(),
        tooltip: 'Agregar Proveedor OIDC',
        child: const Icon(Icons.add),
      ),
    );
  }
}
