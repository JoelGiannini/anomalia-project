import 'package:flutter/material.dart';
import 'screens/login_screen.dart';

void main() {
  runApp(const AnomaliaApp());
}

class AnomaliaApp extends StatelessWidget {
  const AnomaliaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'anomalIAGW',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blueGrey),
        useMaterial3: true,
      ),
      home: const LoginScreen(),
      debugShowCheckedModeBanner: false,
    );
  }
}
