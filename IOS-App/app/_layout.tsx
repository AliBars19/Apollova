import React from 'react';
import { Stack, useRouter, useSegments } from 'expo-router';
import { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { View, StyleSheet } from 'react-native';
import { Colors } from '../constants/colors';
import { useConnectionStore } from '../store/connectionStore';
import { useConnection } from '../hooks/useConnection';
import { useProgress } from '../hooks/useProgress';
import OfflineScreen from '../components/OfflineScreen';

export default function RootLayout(): React.JSX.Element {
  const router = useRouter();
  const segments = useSegments();
  const isPaired = useConnectionStore((s) => s.isPaired);
  const isOnline = useConnectionStore((s) => s.isOnline);

  useConnection();
  useProgress();

  useEffect(() => {
    const inPairScreen = segments[0] === 'pair';

    if (!isPaired && !inPairScreen) {
      router.replace('/pair');
    } else if (isPaired && inPairScreen) {
      router.replace('/(tabs)');
    }
  }, [isPaired, segments, router]);

  return (
    <View style={styles.container}>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: Colors.bg.primary },
          animation: 'fade',
        }}
      >
        <Stack.Screen name="pair" options={{ gestureEnabled: false }} />
        <Stack.Screen name="(tabs)" options={{ gestureEnabled: false }} />
      </Stack>

      {isPaired && !isOnline && <OfflineScreen />}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bg.primary,
  },
});
