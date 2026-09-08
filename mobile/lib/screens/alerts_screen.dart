import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../models/alert_model.dart';

class AlertsScreen extends StatefulWidget {
  const AlertsScreen({super.key});

  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

class _AlertsScreenState extends State<AlertsScreen> with SingleTickerProviderStateMixin {
  late TabController _tabController;
  bool _isLoading = false;
  List<AlertItem> _recentAlerts = [];
  List<AlertItem> _historyAlerts = [];

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _fetchAllerts();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _fetchAllerts() async {
    setState(() => _isLoading = true);
    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('access_token') ?? '';
      
      // Ajusta la URL base de tu backend según corresponda
      const baseUrl = 'http://10.0.2.2:8000/api/v1'; 

      // Petición para alertas recientes / activas
      final recentResponse = await http.get(
        Uri.parse('$baseUrl/alerts/recent'),
        headers: {'Authorization': 'Bearer $token'},
      );

      // Petición para el historial completo de la BD
      final historyResponse = await http.get(
        Uri.parse('$baseUrl/alerts/history'),
        headers: {'Authorization': 'Bearer $token'},
      );

      if (recentResponse.statusCode == 200 && historyResponse.statusCode == 200) {
        final List recentData = json.decode(recentResponse.body)['alerts'] ?? [];
        final List historyData = json.decode(historyResponse.body)['alerts'] ?? [];

        setState(() {
          _recentAlerts = recentData.map((e) => AlertItem.fromJson(e)).toList();
          _historyAlerts = historyData.map((e) => AlertItem.fromJson(e)).toList();
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error al sincronizar alertas: $e'), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Centro de Alertas e Inteligencia'),
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(icon: Icon(Icons.bolt), text: 'Recientes'),
            Tab(icon: Icon(Icons.history), text: 'Historial BD'),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _isLoading ? null : _fetchAllerts,
            tooltip: 'Actualizar',
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : TabBarView(
              controller: _tabController,
              children: [
                _buildAlertsList(_recentAlerts, 'No hay alertas recientes.'),
                _buildAlertsList(_historyAlerts, 'No hay registros en el historial.'),
              ],
            ),
    );
  }

  Widget _buildAlertsList(List<AlertItem> alerts, String emptyMessage) {
    if (alerts.isEmpty) {
      return Center(
        child: Text(
          emptyMessage,
          style: const TextStyle(fontSize: 16, color: Colors.grey),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _fetchAllerts,
      child: ListView.builder(
        padding: const EdgeInsets.all(12.0),
        itemCount: alerts.length,
        itemBuilder: (context, index) {
          final alert = alerts[index];
          final bool isCritical = alert.severity.toLowerCase() == 'critical' || alert.severity.toLowerCase() == 'error';

          return Card(
            elevation: 2,
            margin: const EdgeInsets.symmetric(vertical: 8.0),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            child: ExpansionTile(
              leading: CircleAvatar(
                backgroundColor: isCritical ? Colors.redAccent : Colors.orangeAccent,
                child: Icon(
                  isCritical ? Icons.error_outline : Icons.warning_amber_rounded,
                  color: Colors.white,
                ),
              ),
              title: Text(
                alert.alertname,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              subtitle: Text(
                'Estado: ${alert.status} | Severidad: ${alert.severity}',
                style: TextStyle(color: Colors.grey[700], fontSize: 12),
              ),
              children: [
                Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Descripción:', style: TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 4),
                      Text(alert.description),
                      const SizedBox(height: 12),
                      const Text('Análisis del Motor de IA:', style: TextStyle(fontWeight: FontWeight.bold, color: Colors.indigo)),
                      const SizedBox(height: 4),
                      Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: Colors.indigo.withOpacity(0.05),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: Colors.indigo.withOpacity(0.2)),
                        ),
                        child: Text(alert.aiAnalysis),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
