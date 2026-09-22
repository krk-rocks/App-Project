import { Canvas, useFrame } from '@react-three/fiber'
import { Float, MeshDistortMaterial, Sparkles, Environment, Lightformer } from '@react-three/drei'
import { useRef, useMemo } from 'react'
import * as THREE from 'three'

function Rig() {
  useFrame(({ camera, pointer }, dt) => {
    camera.position.x = THREE.MathUtils.damp(camera.position.x, pointer.x * 0.9, 3, dt)
    camera.position.y = THREE.MathUtils.damp(camera.position.y, pointer.y * 0.5, 3, dt)
    camera.lookAt(0, 0, 0)
  })
  return null
}

function Planet({ hue }) {
  const group = useRef()
  const ring = useRef()
  const color = useMemo(() => new THREE.Color().setHSL(hue / 360, 0.75, 0.55), [hue])
  const accent = useMemo(() => new THREE.Color().setHSL(((hue + 40) % 360) / 360, 0.9, 0.65), [hue])
  useFrame((s, dt) => {
    group.current.rotation.y += dt * 0.25
    ring.current.rotation.z += dt * 0.15
  })
  return (
    <Float speed={1.6} rotationIntensity={0.3} floatIntensity={1.2}>
      <group ref={group}>
        <mesh>
          {/* fewer segments than before - a distorted sphere doesn't need 96x96 to read as smooth */}
          <sphereGeometry args={[1.4, 48, 48]} />
          <MeshDistortMaterial color={color} distort={0.35} speed={1.8} roughness={0.15} metalness={0.4} />
        </mesh>
        <mesh scale={1.02}>
          <icosahedronGeometry args={[1.45, 2]} />
          <meshBasicMaterial color={accent} wireframe transparent opacity={0.18} />
        </mesh>
      </group>
      <mesh ref={ring} rotation={[1.2, 0.2, 0]}>
        <torusGeometry args={[2.3, 0.02, 8, 120]} />
        <meshBasicMaterial color={accent} />
      </mesh>
    </Float>
  )
}

// Cheap stand-in for glass: no real-time transmission (which forces an extra
// full-scene render pass per bubble). Low roughness + transparency reads as
// glassy at a fraction of the GPU cost.
function Bubble({ position, scale, speed }) {
  return (
    <Float speed={speed} floatIntensity={2} rotationIntensity={0.4}>
      <mesh position={position} scale={scale}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshPhysicalMaterial roughness={0.05} metalness={0.1} transparent opacity={0.35} color="#ffffff" envMapIntensity={1.4} />
      </mesh>
    </Float>
  )
}

// A little toy train orbiting the planet - carriages follow the loco with a
// short delay along the same elliptical path, wheels spin as they go.
function Train({ radius = 3.1, speed = 0.35 }) {
  const group = useRef()
  const wheelsRef = useRef([])
  const cars = 3
  const gap = 0.42

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime() * speed
    group.current.children.forEach((car, i) => {
      const a = t - i * gap
      const x = Math.cos(a) * radius
      const z = Math.sin(a) * radius * 0.55
      car.position.set(x, -0.6, z)
      car.rotation.y = -a + Math.PI / 2
    })
    wheelsRef.current.forEach((w) => w && (w.rotation.x -= 0.25))
  })

  return (
    <group ref={group}>
      {Array.from({ length: cars }).map((_, i) => (
        <group key={i}>
          <mesh castShadow>
            <boxGeometry args={[0.34, 0.16, 0.16]} />
            <meshStandardMaterial color={i === 0 ? '#ff6f61' : '#ffd166'} roughness={0.4} metalness={0.2} />
          </mesh>
          {i === 0 && (
            <mesh position={[0.12, 0.13, 0]}>
              <cylinderGeometry args={[0.06, 0.06, 0.12, 10]} />
              <meshStandardMaterial color="#333" />
            </mesh>
          )}
          {[-0.1, 0.1].map((ox) =>
            [-0.08, 0.08].map((oz) => (
              <mesh
                key={`${ox}-${oz}`}
                ref={(el) => wheelsRef.current.push(el)}
                position={[ox, -0.1, oz]}
                rotation={[Math.PI / 2, 0, 0]}
              >
                <cylinderGeometry args={[0.05, 0.05, 0.03, 12]} />
                <meshStandardMaterial color="#222" />
              </mesh>
            ))
          )}
        </group>
      ))}
    </group>
  )
}

// A small paper-plane silhouette that swoops past on a lazy figure-eight-ish path.
function Plane() {
  const ref = useRef()
  useFrame(({ clock }) => {
    const t = clock.getElapsedTime() * 0.25
    const x = Math.sin(t) * 4.2
    const y = Math.cos(t * 0.6) * 1.4 + 1.6
    const z = Math.cos(t) * 1.8 - 1
    ref.current.position.set(x, y, z)
    ref.current.rotation.z = Math.sin(t) * 0.3
    ref.current.rotation.y = -t + Math.PI / 2
  })
  return (
    <group ref={ref} scale={0.55}>
      <mesh rotation={[0, 0, Math.PI / 2]}>
        <coneGeometry args={[0.12, 0.5, 4]} />
        <meshStandardMaterial color="#f4f2fb" roughness={0.3} flatShading />
      </mesh>
      <mesh position={[-0.05, 0, 0]} rotation={[0, 0.5, 0]}>
        <coneGeometry args={[0.22, 0.05, 3]} />
        <meshStandardMaterial color="#cdb8ff" roughness={0.3} flatShading />
      </mesh>
    </group>
  )
}

// A hot-air balloon drifting slowly up and sideways, basket swaying underneath.
function Balloon({ position = [-3, -1.5, -1.5], hue = 20 }) {
  const ref = useRef()
  const color = useMemo(() => new THREE.Color().setHSL(hue / 360, 0.8, 0.6), [hue])
  useFrame(({ clock }) => {
    const t = clock.getElapsedTime()
    ref.current.position.y = position[1] + Math.sin(t * 0.4) * 0.4
    ref.current.position.x = position[0] + Math.cos(t * 0.25) * 0.5
    ref.current.rotation.z = Math.sin(t * 0.3) * 0.05
  })
  return (
    <group ref={ref} position={position} scale={0.5}>
      <mesh position={[0, 0.4, 0]}>
        <sphereGeometry args={[0.4, 20, 20]} />
        <meshStandardMaterial color={color} roughness={0.5} />
      </mesh>
      <mesh position={[0, -0.15, 0]}>
        <boxGeometry args={[0.16, 0.14, 0.16]} />
        <meshStandardMaterial color="#7a5230" roughness={0.8} />
      </mesh>
    </group>
  )
}

export default function Scene({ hue = 270, bubbles = true, extras = false, className = '' }) {
  return (
    <Canvas
      className={className}
      camera={{ position: [0, 0, 6.5], fov: 45 }}
      dpr={[1, 1.5]}
      gl={{ antialias: false, alpha: true, powerPreference: 'high-performance' }}
    >
      <ambientLight intensity={0.6} />
      <directionalLight position={[4, 5, 3]} intensity={2.2} />
      <pointLight position={[-4, -2, -3]} intensity={30} color={`hsl(${hue},90%,60%)`} />
      <Environment resolution={128}>
        <Lightformer form="rect" intensity={4} position={[0, 5, -6]} scale={[12, 3, 1]} color="#ffd9ff" />
        <Lightformer form="rect" intensity={3} position={[-5, 1, 2]} scale={[3, 6, 1]} color="#9fc4ff" />
        <Lightformer form="circle" intensity={2} position={[5, -2, 2]} scale={4} color="#ffb98a" />
      </Environment>
      <Planet hue={hue} />
      {bubbles && (
        <>
          <Bubble position={[-3.6, 1.2, -0.5]} scale={0.9} speed={1.2} />
          <Bubble position={[3.4, -1.3, 0.4]} scale={0.6} speed={1.6} />
          <Bubble position={[2.6, 2, -1.5]} scale={0.35} speed={2} />
          <Bubble position={[-2.4, -2, 0.8]} scale={0.4} speed={1.8} />
        </>
      )}
      {extras && (
        <>
          <Train />
          <Plane />
          <Balloon position={[-3.2, -1.6, -1.2]} hue={hue + 30} />
          <Balloon position={[3.6, 0.8, -2]} hue={hue - 40} />
        </>
      )}
      <Sparkles count={40} scale={[12, 7, 6]} size={3} speed={0.4} opacity={0.6} />
      <Rig />
    </Canvas>
  )
}
