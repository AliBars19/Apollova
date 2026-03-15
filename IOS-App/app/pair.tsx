import React, { useState, useCallback } from 'react';
import { View, Text, Pressable, StyleSheet, Alert, ActivityIndicator } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as SecureStore from 'expo-secure-store';
import { useRouter } from 'expo-router';
import { Colors } from '../constants/colors';
import { useConnectionStore } from '../store/connectionStore';
import { getHealth } from '../api/endpoints';

interface QrPayload {
  readonly url: string;
  readonly token: string;
}

const SECURE_STORE_URL_KEY = 'apollova_tunnel_url';
const SECURE_STORE_TOKEN_KEY = 'apollova_session_token';

export default function PairScreen(): React.JSX.Element {
  const router = useRouter();
  const setPaired = useConnectionStore((s) => s.setPaired);
  const [permission, requestPermission] = useCameraPermissions();
  const [isCameraOpen, setIsCameraOpen] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [hasScanned, setHasScanned] = useState(false);

  const handleBarCodeScanned = useCallback(
    async (scanResult: { data: string }) => {
      if (hasScanned || isVerifying) {
        return;
      }

      setHasScanned(true);
      setIsVerifying(true);

      try {
        const payload: QrPayload = JSON.parse(scanResult.data);

        if (!payload.url || !payload.token) {
          Alert.alert('Invalid QR Code', 'This QR code does not contain valid Apollova pairing data.');
          setHasScanned(false);
          setIsVerifying(false);
          return;
        }

        useConnectionStore.setState({
          tunnelUrl: payload.url,
          sessionToken: payload.token,
        });

        await getHealth();

        await SecureStore.setItemAsync(SECURE_STORE_URL_KEY, payload.url);
        await SecureStore.setItemAsync(SECURE_STORE_TOKEN_KEY, payload.token);

        setPaired(payload.url, payload.token);
        router.replace('/(tabs)');
      } catch {
        Alert.alert(
          'Connection Failed',
          'Could not connect to your PC. Make sure the Apollova desktop app is running and try again.',
        );
        setHasScanned(false);
        setIsVerifying(false);
      }
    },
    [hasScanned, isVerifying, setPaired, router],
  );

  const handleOpenCamera = async (): Promise<void> => {
    if (!permission?.granted) {
      const result = await requestPermission();
      if (!result.granted) {
        Alert.alert(
          'Camera Permission Required',
          'Apollova needs camera access to scan the QR code from your PC.',
        );
        return;
      }
    }
    setIsCameraOpen(true);
    setHasScanned(false);
  };

  if (isCameraOpen) {
    return (
      <View style={styles.cameraContainer}>
        <CameraView
          style={styles.camera}
          barcodeScannerSettings={{
            barcodeTypes: ['qr'],
          }}
          onBarcodeScanned={hasScanned ? undefined : handleBarCodeScanned}
        >
          <View style={styles.cameraOverlay}>
            <View style={styles.scanFrame} />

            {isVerifying ? (
              <View style={styles.verifyingContainer}>
                <ActivityIndicator size="large" color={Colors.accent.blue} />
                <Text style={styles.verifyingText}>Verifying connection...</Text>
              </View>
            ) : (
              <Text style={styles.scanInstructions}>
                Point your camera at the QR code on your PC
              </Text>
            )}

            <Pressable
              style={styles.cancelButton}
              onPress={() => {
                setIsCameraOpen(false);
                setHasScanned(false);
              }}
            >
              <Text style={styles.cancelText}>Cancel</Text>
            </Pressable>
          </View>
        </CameraView>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.wordmark}>APOLLOVA</Text>
        <Text style={styles.tagline}>Remote control for your lyric video pipeline</Text>

        <Pressable style={styles.scanButton} onPress={handleOpenCamera}>
          <Text style={styles.scanButtonText}>Scan QR Code</Text>
        </Pressable>

        <Text style={styles.helpText}>
          Open the Apollova desktop app on your PC and navigate to Settings to display the pairing
          QR code.
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  content: {
    alignItems: 'center',
    paddingHorizontal: 40,
  },
  wordmark: {
    fontSize: 36,
    fontWeight: '800',
    color: Colors.text.primary,
    letterSpacing: 8,
    marginBottom: 12,
  },
  tagline: {
    fontSize: 15,
    color: Colors.text.secondary,
    textAlign: 'center',
    marginBottom: 60,
  },
  scanButton: {
    backgroundColor: Colors.accent.blue,
    paddingHorizontal: 40,
    paddingVertical: 16,
    borderRadius: 14,
    marginBottom: 24,
  },
  scanButtonText: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.bg.primary,
  },
  helpText: {
    fontSize: 13,
    color: Colors.text.disabled,
    textAlign: 'center',
    lineHeight: 20,
    maxWidth: 280,
  },
  cameraContainer: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
  },
  camera: {
    flex: 1,
  },
  cameraOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  scanFrame: {
    width: 250,
    height: 250,
    borderWidth: 2,
    borderColor: Colors.accent.blue,
    borderRadius: 16,
    marginBottom: 32,
  },
  scanInstructions: {
    fontSize: 15,
    color: Colors.text.primary,
    textAlign: 'center',
    marginBottom: 40,
  },
  verifyingContainer: {
    alignItems: 'center',
    marginBottom: 40,
  },
  verifyingText: {
    fontSize: 15,
    color: Colors.text.primary,
    marginTop: 12,
  },
  cancelButton: {
    paddingHorizontal: 24,
    paddingVertical: 12,
  },
  cancelText: {
    fontSize: 16,
    color: Colors.status.danger,
    fontWeight: '600',
  },
});
