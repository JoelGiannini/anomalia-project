class AlertItem {
  final int? id;
  final String alertname;
  final String severity;
  final String summary;
  final String description;
  final String aiAnalysis;
  final String status;
  final String createdAt;

  AlertItem({
    this.id,
    required this.alertname,
    required this.severity,
    required this.summary,
    required this.description,
    required this.aiAnalysis,
    required this.status,
    required this.createdAt,
  });

  factory AlertItem.fromJson(Map<String, dynamic> json) {
    return AlertItem(
      id: json['id'],
      alertname: json['alertname'] ?? json['labels']?['alertname'] ?? 'Alerta Desconocida',
      severity: json['severity'] ?? json['labels']?['severity'] ?? 'warning',
      summary: json['summary'] ?? json['annotations']?['summary'] ?? 'Sin resumen',
      description: json['description'] ?? json['annotations']?['description'] ?? 'Sin descripción',
      aiAnalysis: json['ai_analysis'] ?? json['analysis'] ?? 'Sin análisis de IA disponible.',
      status: json['status'] ?? 'firing',
      createdAt: json['created_at'] ?? DateTime.now().toString(),
    );
  }
}
