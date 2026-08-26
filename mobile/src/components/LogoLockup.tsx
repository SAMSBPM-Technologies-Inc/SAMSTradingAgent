import React from 'react'
import { View, Text, Platform } from 'react-native'
import Svg, { Rect, Path } from 'react-native-svg'
import { usePalette } from '../lib/palette'

/**
 * The SAMSBPM mark and wordmark — the phone copy of the web `LogoLockup` in
 * `frontend/src/components/Layout.tsx`. Geometry, viewBox and stroke weights
 * are the same numbers, so the two render the same mark at any size.
 *
 * The mark is a rising line closing on an arrowhead, not a lettermark.
 */

export function IconMark({ size = 28 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 34 34">
      <Rect width="34" height="34" rx="8" fill="#f2600c" />
      <Path
        d="M9 23L15 17L19 20L25 11"
        stroke="white" strokeWidth={2.5}
        strokeLinecap="round" strokeLinejoin="round" fill="none"
      />
      <Path
        d="M25 11H19M25 11V17"
        stroke="white" strokeWidth={2.5}
        strokeLinecap="round" strokeLinejoin="round" fill="none"
      />
    </Svg>
  )
}

/**
 * Stacked wordmark: SAMSBPM in ink over a rule over TRADING AGENT in orange.
 *
 * The web side sets the wordmark in Fraunces. That font is not bundled on
 * mobile, so this falls back to the platform serif rather than silently
 * rendering the system sans and losing the distinction the design draws
 * between the name and the product line.
 */
export default function LogoLockup({ compact = false, size = 28 }: {
  compact?: boolean
  size?: number
}) {
  const C = usePalette()

  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 9 }}>
      <IconMark size={size} />
      {!compact && (
        <View style={{ alignItems: 'center', gap: 3 }}>
          <Text style={{
            color: C.fg,
            fontFamily: Platform.select({ ios: 'Georgia', android: 'serif' }),
            fontWeight: '600',
            fontSize: 15,
            lineHeight: 16,
          }}>
            SAMSBPM
          </Text>
          <View style={{ height: 1, alignSelf: 'stretch', backgroundColor: C.border }} />
          <Text style={{
            color: C.brand,
            fontSize: 8.5,
            lineHeight: 10,
            fontWeight: '600',
            letterSpacing: 1.55,
            textTransform: 'uppercase',
          }}>
            Trading Agent
          </Text>
        </View>
      )}
    </View>
  )
}
