import 'package:flutter/material.dart';
import '../services/api_service.dart';

class AbmScreen extends StatefulWidget {
  const AbmScreen({super.key});

  @override
  State<AbmScreen> createState() => _AbmScreenState();
}

class _AbmScreenState extends State<AbmScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  List<dynamic> _users = [];
  List<dynamic> _roles = [];
  List<dynamic> _profiles = [];
  bool _isLoading = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    _tabController.addListener(() {
      setState(() {});
    });
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final usersData = await ApiService.getUsers();
      final rolesData = await ApiService.getRoles();
      
      List<dynamic> profilesData = [];
      try {
        profilesData = await ApiService.getProfiles();
      } catch (_) {
        profilesData = [];
      }

      setState(() {
        _users = usersData;
        _roles = rolesData;
        _profiles = profilesData;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _errorMessage = e.toString().replaceAll('Exception: ', '');
        _isLoading = false;
      });
    }
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  // --- MODAL PARA CREAR / EDITAR USUARIO ---
  void _showUserModal({Map<String, dynamic>? user}) {
    final emailController = TextEditingController(text: user?['username'] ?? '');
    final passwordController = TextEditingController();
    final confirmPasswordController = TextEditingController();
    
    List<String> selectedRoles = [];
    if (user != null) {
      if (user['roles'] is List) {
        selectedRoles = List<String>.from(user['roles']);
      } else if (user['role'] != null) {
        selectedRoles = [user['role'].toString()];
      }
    }

    showDialog(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setStateModal) {
            return AlertDialog(
              title: Text(user == null ? 'Nuevo Usuario' : 'Editar Usuario'),
              content: SizedBox(
                width: double.maxFinite,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      TextField(
                        controller: emailController,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(
                          labelText: 'Correo Electrónico (Usuario)',
                          hintText: 'usuario@dominio.com',
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: passwordController,
                        obscureText: true,
                        decoration: InputDecoration(
                          labelText: 'Contraseña',
                          hintText: user == null ? 'Obligatorio' : 'Dejar en blanco para no cambiar',
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: confirmPasswordController,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Confirmar Contraseña',
                          hintText: 'Repite la contraseña',
                        ),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'Roles del Usuario',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                      ),
                      const SizedBox(height: 8),
                      _roles.isEmpty
                          ? const Text('No hay roles disponibles', style: TextStyle(color: Colors.grey))
                          : Container(
                              constraints: const BoxConstraints(maxHeight: 180),
                              width: double.maxFinite,
                              child: ListView.builder(
                                shrinkWrap: true,
                                itemCount: _roles.length,
                                itemBuilder: (context, index) {
                                  final roleName = _roles[index]['name'].toString();
                                  final isSelected = selectedRoles.contains(roleName);
                                  return CheckboxListTile(
                                    title: Text(roleName),
                                    value: isSelected,
                                    dense: true,
                                    contentPadding: EdgeInsets.zero,
                                    onChanged: (bool? value) {
                                      setStateModal(() {
                                        if (value == true) {
                                          if (!selectedRoles.contains(roleName)) {
                                            selectedRoles.add(roleName);
                                          }
                                        } else {
                                          selectedRoles.remove(roleName);
                                        }
                                      });
                                    },
                                  );
                                },
                              ),
                            ),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Cancelar'),
                ),
                ElevatedButton(
                  onPressed: () async {
                    final emailText = emailController.text.trim();
                    if (emailText.isEmpty || !emailText.contains('@')) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Ingrese un correo electrónico válido'), backgroundColor: Colors.red),
                      );
                      return;
                    }

                    if (selectedRoles.isEmpty) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Debe seleccionar al menos un rol'), backgroundColor: Colors.red),
                      );
                      return;
                    }

                    if (passwordController.text.isNotEmpty || user == null) {
                      if (passwordController.text != confirmPasswordController.text) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('Las contraseñas no coinciden'), backgroundColor: Colors.red),
                        );
                        return;
                      }
                      if (user == null && passwordController.text.isEmpty) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('La contraseña es obligatoria para nuevos usuarios'), backgroundColor: Colors.red),
                        );
                        return;
                      }
                    }

                    try {
                      final body = {
                        'username': emailText,
                        'name': emailText,
                        'email': emailText,
                        'roles': selectedRoles,
                      };
                      
                      if (passwordController.text.isNotEmpty) {
                        body['password'] = passwordController.text;
                        body['confirm_password'] = confirmPasswordController.text;
                      }

                      if (user == null) {
                        await ApiService.createUser(body);
                      } else {
                        await ApiService.updateUser(user['id'].toString(), body);
                      }

                      if (!mounted) return;
                      Navigator.pop(context);
                      _loadData();
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Usuario guardado correctamente')),
                      );
                    } catch (e) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text('Error: ${e.toString().replaceAll('Exception: ', '')}'), backgroundColor: Colors.red),
                      );
                    }
                  },
                  child: const Text('Guardar'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  // --- MODAL PARA CREAR / EDITAR ROL ---
  void _showRoleModal({Map<String, dynamic>? role}) {
    final nameController = TextEditingController(text: role?['name'] ?? '');
    final descController = TextEditingController(text: role?['description'] ?? '');

    List<String> selectedProfiles = [];
    if (role != null) {
      if (role['profiles'] is List) {
        selectedProfiles = List<String>.from(role['profiles']);
      } else if (role['profile'] != null) {
        selectedProfiles = [role['profile'].toString()];
      }
    }

    showDialog(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setStateModal) {
            return AlertDialog(
              title: Text(role == null ? 'Nuevo Rol' : 'Editar Rol'),
              content: SizedBox(
                width: double.maxFinite,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      TextField(
                        controller: nameController,
                        decoration: const InputDecoration(labelText: 'Nombre del Rol'),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: descController,
                        decoration: const InputDecoration(labelText: 'Descripción'),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'Perfiles Asociados (Accesos)',
                        style: TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
                      ),
                      const SizedBox(height: 8),
                      _profiles.isEmpty
                          ? const Text('No hay perfiles disponibles. Cree perfiles primero.', style: TextStyle(color: Colors.grey))
                          : Container(
                              constraints: const BoxConstraints(maxHeight: 180),
                              width: double.maxFinite,
                              child: ListView.builder(
                                shrinkWrap: true,
                                itemCount: _profiles.length,
                                itemBuilder: (context, index) {
                                  final profileName = _profiles[index]['name'].toString();
                                  final isSelected = selectedProfiles.contains(profileName);
                                  return CheckboxListTile(
                                    title: Text(profileName),
                                    subtitle: Text(_profiles[index]['description'] ?? '', style: const TextStyle(fontSize: 12)),
                                    value: isSelected,
                                    dense: true,
                                    contentPadding: EdgeInsets.zero,
                                    onChanged: (bool? value) {
                                      setStateModal(() {
                                        if (value == true) {
                                          if (!selectedProfiles.contains(profileName)) {
                                            selectedProfiles.add(profileName);
                                          }
                                        } else {
                                          selectedProfiles.remove(profileName);
                                        }
                                      });
                                    },
                                  );
                                },
                              ),
                            ),
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Cancelar'),
                ),
                ElevatedButton(
                  onPressed: () async {
                    if (nameController.text.isEmpty) return;

                    try {
                      final body = {
                        'name': nameController.text,
                        'description': descController.text,
                        'profiles': selectedProfiles,
                      };

                      if (role == null) {
                        await ApiService.createRole(body);
                      } else {
                        await ApiService.updateRole(role['id'].toString(), body);
                      }

                      if (!mounted) return;
                      Navigator.pop(context);
                      _loadData();
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Rol guardado correctamente')),
                      );
                    } catch (e) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text('Error: ${e.toString().replaceAll('Exception: ', '')}'), backgroundColor: Colors.red),
                      );
                    }
                  },
                  child: const Text('Guardar'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  // --- MODAL PARA CREAR / EDITAR PERFIL ---
  void _showProfileModal({Map<String, dynamic>? profile}) {
    final nameController = TextEditingController(text: profile?['name'] ?? '');
    final descController = TextEditingController(text: profile?['description'] ?? '');

    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: Text(profile == null ? 'Nuevo Perfil' : 'Editar Perfil'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameController,
                decoration: const InputDecoration(labelText: 'Nombre del Perfil'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: descController,
                decoration: const InputDecoration(labelText: 'Descripción'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancelar'),
            ),
            ElevatedButton(
              onPressed: () async {
                if (nameController.text.trim().isEmpty) return;

                try {
                  final body = {
                    'name': nameController.text.trim(),
                    'description': descController.text.trim(),
                  };

                  if (profile == null) {
                    await ApiService.createProfile(body);
                  } else {
                    await ApiService.updateProfile(profile['id'].toString(), body);
                  }

                  if (!mounted) return;
                  Navigator.pop(context);
                  _loadData();
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Perfil guardado correctamente')),
                  );
                } catch (e) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Error: ${e.toString().replaceAll('Exception: ', '')}'), backgroundColor: Colors.red),
                  );
                }
              },
              child: const Text('Guardar'),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Panel de Administración ABM'),
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(icon: Icon(Icons.people), text: 'Usuarios'),
            Tab(icon: Icon(Icons.security), text: 'Roles'),
            Tab(icon: Icon(Icons.badge), text: 'Perfiles'),
          ],
        ),
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _errorMessage != null
              ? Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text('Error: $_errorMessage', style: const TextStyle(color: Colors.red)),
                      const SizedBox(height: 12),
                      ElevatedButton(
                        onPressed: _loadData,
                        child: const Text('Reintentar'),
                      ),
                    ],
                  ),
                )
              : TabBarView(
                  controller: _tabController,
                  children: [
                    // 1. VISTA DE USUARIOS
                    RefreshIndicator(
                      onRefresh: _loadData,
                      child: ListView.builder(
                        itemCount: _users.length,
                        padding: const EdgeInsets.all(8),
                        itemBuilder: (context, index) {
                          final user = _users[index];
                          final username = user['username'] ?? user['name'] ?? 'Sin usuario';
                          
                          String rolesText = 'Sin roles';
                          if (user['roles'] is List) {
                            rolesText = (user['roles'] as List).join(', ');
                          } else if (user['role'] != null) {
                            rolesText = user['role'].toString();
                          }

                          return Card(
                            child: ListTile(
                              leading: CircleAvatar(
                                child: Text(username.isNotEmpty ? username[0].toUpperCase() : 'U'),
                              ),
                              title: Text(username),
                              subtitle: Text('Roles: $rolesText'),
                              trailing: PopupMenuButton<String>(
                                onSelected: (value) async {
                                  if (value == 'edit') {
                                    _showUserModal(user: user);
                                  } else if (value == 'delete') {
                                    try {
                                      await ApiService.deleteUser(user['id'].toString());
                                      _loadData();
                                      if (!mounted) return;
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        const SnackBar(content: Text('Usuario eliminado')),
                                      );
                                    } catch (e) {
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red),
                                      );
                                    }
                                  }
                                },
                                itemBuilder: (context) => [
                                  const PopupMenuItem(value: 'edit', child: Text('Editar')),
                                  const PopupMenuItem(value: 'delete', child: Text('Eliminar')),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                    ),

                    // 2. VISTA DE ROLES
                    RefreshIndicator(
                      onRefresh: _loadData,
                      child: ListView.builder(
                        itemCount: _roles.length,
                        padding: const EdgeInsets.all(8),
                        itemBuilder: (context, index) {
                          final role = _roles[index];
                          
                          String profilesText = 'Sin perfiles';
                          if (role['profiles'] is List) {
                            profilesText = (role['profiles'] as List).join(', ');
                          } else if (role['profile'] != null) {
                            profilesText = role['profile'].toString();
                          }

                          return Card(
                            child: ListTile(
                              leading: const Icon(Icons.admin_panel_settings),
                              title: Text(role['name'] ?? ''),
                              subtitle: Text('${role['description'] ?? ''}\nPerfiles: $profilesText'),
                              isThreeLine: true,
                              trailing: PopupMenuButton<String>(
                                onSelected: (value) async {
                                  if (value == 'edit') {
                                    _showRoleModal(role: role);
                                  } else if (value == 'delete') {
                                    try {
                                      await ApiService.deleteRole(role['id'].toString());
                                      _loadData();
                                      if (!mounted) return;
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        const SnackBar(content: Text('Rol eliminado')),
                                      );
                                    } catch (e) {
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red),
                                      );
                                    }
                                  }
                                },
                                itemBuilder: (context) => [
                                  const PopupMenuItem(value: 'edit', child: Text('Editar')),
                                  const PopupMenuItem(value: 'delete', child: Text('Eliminar')),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                    ),

                    // 3. VISTA DE PERFILES
                    RefreshIndicator(
                      onRefresh: _loadData,
                      child: ListView.builder(
                        itemCount: _profiles.length,
                        padding: const EdgeInsets.all(8),
                        itemBuilder: (context, index) {
                          final profile = _profiles[index];
                          return Card(
                            child: ListTile(
                              leading: const Icon(Icons.badge),
                              title: Text(profile['name'] ?? ''),
                              subtitle: Text(profile['description'] ?? ''),
                              trailing: PopupMenuButton<String>(
                                onSelected: (value) async {
                                  if (value == 'edit') {
                                    _showProfileModal(profile: profile);
                                  } else if (value == 'delete') {
                                    try {
                                      await ApiService.deleteProfile(profile['id'].toString());
                                      _loadData();
                                      if (!mounted) return;
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        const SnackBar(content: Text('Perfil eliminado')),
                                      );
                                    } catch (e) {
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red),
                                      );
                                    }
                                  }
                                },
                                itemBuilder: (context) => [
                                  const PopupMenuItem(value: 'edit', child: Text('Editar')),
                                  const PopupMenuItem(value: 'delete', child: Text('Eliminar')),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ],
                ),
      floatingActionButton: FloatingActionButton(
        onPressed: () {
          if (_tabController.index == 0) {
            _showUserModal();
          } else if (_tabController.index == 1) {
            _showRoleModal();
          } else {
            _showProfileModal();
          }
        },
        child: const Icon(Icons.add),
      ),
    );
  }
}
