import React, { useEffect, useRef } from 'react';
import { View, Animated, StyleSheet } from 'react-native';
import { Colors } from '../constants/colors';

interface ProgressBarProps {
  readonly percent: number;
  readonly height?: number;
}

export default function ProgressBar({ percent, height = 8 }: ProgressBarProps): React.JSX.Element {
  const animatedWidth = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(animatedWidth, {
      toValue: percent,
      duration: 400,
      useNativeDriver: false,
    }).start();
  }, [percent, animatedWidth]);

  const widthInterpolation = animatedWidth.interpolate({
    inputRange: [0, 100],
    outputRange: ['0%', '100%'],
    extrapolate: 'clamp',
  });

  return (
    <View style={[styles.track, { height }]}>
      <Animated.View style={[styles.fill, { width: widthInterpolation, height }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    width: '100%',
    backgroundColor: Colors.bg.elevated,
    borderRadius: 4,
    overflow: 'hidden',
  },
  fill: {
    borderRadius: 4,
    backgroundColor: Colors.brand.mid,
  },
});
